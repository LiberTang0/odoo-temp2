# -*- coding: utf-8 -*-
from openerp.osv import orm, fields, osv
from datetime import datetime as dt
from dateutil.relativedelta import relativedelta as rd
from openerp import SUPERUSER_ID
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF
import psycopg2
import logging

_logger = logging.getLogger(__name__)


def browse_domain(self, cr, uid, domain, limit=None, order=None, context=None):
    ids = self.search(cr, uid, domain, limit=limit, order=order, context=context)
    return self.browse(cr, uid, ids, context)


orm.Model.browse_domain = browse_domain


def read_domain(self, cr, uid, domain, fields=[], context=None):
    ids = self.search(cr, uid, domain, context=context)
    return self.read(cr, uid, ids, fields, context)


orm.Model.read_domain = read_domain


def except_if(test=True, cap="Exception!", msg="Message is not defined..."):
    if test:
        raise orm.except_orm(cap, msg)

class Event(object):
    def __init__(self, **kwargs):
        self.model = kwargs.get('model', None)
        self.method = kwargs.get('method', None)
        self.activity =kwargs.get('activity', None)
        self.data = kwargs.get('data', None)
        self.args = kwargs.get('args', [])
        self.kwargs  = kwargs.get('kwargs', {})
    
    def __repr__(self):
        res = "%s::%s()" % (self.model, self.method)
        return res


def data_model_event(callback=None):
    def decorator(f):
        def wrapper(*args, **kwargs):
            self, cr, uid, activity_id = args[:4]
            if isinstance(activity_id, list) and len(activity_id) == 1:
                activity_id = activity_id[0]
            assert isinstance(activity_id, (int, long)) and activity_id > 0, \
                "activity_id must be INT or LONG and > 0, found type='%s', value=%s, f='%s'" \
                % (type(activity_id), activity_id, f)
            activity = self.browse(cr, uid, activity_id)
            data_model = self.pool[activity.data_model]
            
            handlers = [h for h in self._handlers
                         if h['trigger_model'] == activity.data_model and h['trigger_method'] == f.__name__]
            
            if handlers: # run before handlers
                event = Event(model=data_model, method=f.__name__, activity=activity, 
                              data=activity.data_ref, args=args, kwargs=kwargs)
                [eval("self.pool['%s'].%s(cr, uid[1], args[2], event)" % (h['handler_model'], h['handler_method']))
                  for h in handlers if h['when'] == 'before']
            
            f(*args, **kwargs) # FIXME: should we execute this f at all?
            res = eval("data_model.%s(*args[1:], **kwargs)" % f.__name__)
            
            if handlers: # run after handlers
                activity = self.browse(cr, uid, activity_id)
                event = Event(model=data_model, method=f.__name__, activity=activity, 
                              data=activity.data_ref, args=args, kwargs=kwargs)
                [eval("self.pool['%s'].%s(cr, uid, event)" % (h['handler_model'], h['handler_method']))
                    for h in handlers if h['when'] == 'after']
            return res

        return wrapper

    return decorator




class nh_activity(orm.Model):
    """ activity
    """

    _name = 'nh.activity'
    _rec_name = 'summary'

    _states = [('new', 'new'), ('planned', 'Planned'), ('scheduled', 'Scheduled'),
               ('started', 'Started'), ('completed', 'Completed'), ('cancelled', 'Cancelled'),
               ('suspended', 'Suspended'), ('aborted', 'Aborted'), ('expired', 'Expired')]
    
    _handlers = []

    def _register_handler(self, trigger_model, trigger_method, handler_model, handler_method, when='after'):
        h = {'trigger_model': trigger_model, 'trigger_method': trigger_method,
                               'handler_model': handler_model, 'handler_method': handler_method,
                               'when': when}
        if h not in self._handlers: self._handlers.append(h)
        
    def _get_data_type_selection(self, cr, uid, context=None):

        res = [(model_name, model._description) for model_name, model in self.pool.models.items()
                           if hasattr(model, '_description')]        
        return res

    def _is_schedule_allowed(self, cr, uid, ids, field, arg, context=None):
        res = {}
        for activity in self.browse(cr, uid, ids, context):
            res[activity.id] = self.pool[activity.data_model].is_action_allowed(activity.state, 'schedule') \
                               and activity.data_ref._schedule_view_xmlid
        return res

    def _is_start_allowed(self, cr, uid, ids, field, arg, context=None):
        res = {}
        for activity in self.browse(cr, uid, ids, context):
            res[activity.id] = self.pool[activity.data_model].is_action_allowed(activity.state, 'start') \
                               and activity.data_ref._start_view_xmlid
        return res

    def _is_submit_allowed(self, cr, uid, ids, field, arg, context=None):
        res = {}
        for activity in self.browse(cr, uid, ids, context):
            res[activity.id] = self.pool[activity.data_model].is_action_allowed(activity.state, 'submit') \
                               and activity.data_ref._submit_view_xmlid
        return res

    def _is_complete_allowed(self, cr, uid, ids, field, arg, context=None):
        res = {}
        for activity in self.browse(cr, uid, ids, context):
            res[activity.id] = self.pool[activity.data_model].is_action_allowed(activity.state, 'complete') \
                               and activity.data_ref._complete_view_xmlid
        return res

    def _is_cancel_allowed(self, cr, uid, ids, field, arg, context=None):
        res = {}
        for activity in self.browse(cr, uid, ids, context):
            res[activity.id] = self.pool[activity.data_model].is_action_allowed(activity.state, 'cancel') \
                               and activity.data_ref._cancel_view_xmlid
        return res


    
    _columns = {
        'summary': fields.char('Summary', size=256),

        # hierarchies
        'parent_id': fields.many2one('nh.activity', 'Parent activity', readonly=True,
                                     help="Business hierarchy"),
        'child_ids': fields.one2many('nh.activity', 'parent_id', 'Child Activities', readonly=True),
        'creator_id': fields.many2one('nh.activity', 'Creator activity', readonly=True,
                                      help="Evolution hierarchy"),
        'created_ids': fields.one2many('nh.activity', 'creator_id', 'Created Activities', readonly=True),
        # state
        'notes': fields.text('Notes'),
        'state': fields.selection(_states, 'State', readonly=True),
        # identification
        'user_id': fields.many2one('res.users', 'Assignee', readonly=True),
        # system data
        'create_date': fields.datetime('Create Date', readonly=True),
        'write_date': fields.datetime('Write Date', readonly=True),
        'create_uid': fields.many2one('res.users', 'Created By', readonly=True),
        'write_uid': fields.many2one('res.users', 'Updated By', readonly=True),
        'terminate_uid': fields.many2one('res.users', 'Completed By', readonly=True),
        # dates planning
        'date_planned': fields.datetime('Planned Time', readonly=True),
        'date_scheduled': fields.datetime('Scheduled Time', readonly=True),
        #dates actions
        'date_started': fields.datetime('Started Time', readonly=True),
        'date_terminated': fields.datetime('Termination Time', help="Completed, Aborted, Expired, Cancelled", readonly=True),
        # dates limits
        'date_deadline': fields.datetime('Deadline Time', readonly=True),
        'date_expiry': fields.datetime('Expiry Time', readonly=True),
        # activity type and related model/resource
        'data_model': fields.text("Data Model", required=True),
        'data_ref': fields.reference('Data Reference', _get_data_type_selection, size=256, readonly=True),
        # UI actions
        'is_schedule_allowed': fields.function(_is_schedule_allowed, type='boolean', string='Is Schedule Allowed?'),
        'is_start_allowed': fields.function(_is_start_allowed, type='boolean', string='Is Start Allowed?'),
        'is_submit_allowed': fields.function(_is_submit_allowed, type='boolean', string='Is Submit Allowed?'),
        'is_complete_allowed': fields.function(_is_complete_allowed, type='boolean', string='Is Complete Allowed?'),
        'is_cancel_allowed': fields.function(_is_cancel_allowed, type='boolean', string='Is Cancel Allowed?'),
        # order
        'sequence': fields.integer("State Switch Sequence"),
    }

    _sql_constrints = {
        ('data_ref_unique', 'unique(data_ref)', 'Data reference must be unique!'),
    }

    _defaults = {
        'state': 'new',
        #'summary': 'Not specified',
    }

    def create(self, cr, uid, vals, context=None):
        except_if(not vals.get('data_model'), msg="data_model is not defined!")
        data_model_pool = self.pool.get(vals['data_model'])
        except_if(not data_model_pool, msg="data_model does not exist in the model pool!")
        not vals.get('summary') and vals.update({'summary': data_model_pool._description})           
        activity_id = super(nh_activity, self).create(cr, uid, vals, context)
        _logger.debug("activity '%s' created, activity.id=%s" % (vals.get('data_model'), activity_id))
        return activity_id

    def write(self, cr, uid, ids, vals, context=None):
        if 'state' in vals:
            cr.execute("select coalesce(max(sequence), 0) from nh_activity")
            sequence = cr.fetchone()[0] + 1
            vals.update({'sequence': sequence})     
            _logger.debug("Sequence set to: %s" % sequence)    
        res = super(nh_activity, self).write(cr, uid, ids, vals, context)
        return res
    
    
    def activity_rank_map(self, cr, uid, 
                        partition_by="user_id", where=None, 
                        partition_order="id desc", 
                        rank_order="desc", limit=None):
        
        args = {
                  "partition_by": partition_by,
                  "where": where and "where %s" % where or "",
                  "partition_order": partition_order,
                  "rank_order": rank_order,
                  "limit": limit and "limit %s" % limit or ""
                }
        sql = """
            select 
                id,
                rank() over (partition by %(partition_by)s order by %(partition_order)s) as rank
            from nh_activity
            %(where)s
            order by rank %(rank_order)s
            %(limit)s
        """ % args
        cr.execute(sql)
        res = {activity['rank']:activity['id'] for activity in cr.dictfetchall()}
        return res 
    # DATA API

    @data_model_event(callback="start_act_window")
    def start_act_window(self, cr, uid, activity_id, fields, context=None):
        return {}

    @data_model_event(callback="schedule_act_window")
    def schedule_act_window(self, cr, uid, activity_id, fields, context=None):
        return {}

    @data_model_event(callback="submit_act_window")
    def submit_act_window(self, cr, uid, activity_id, fields, context=None):
        return {}

    @data_model_event(callback="complete_act_window")
    def complete_act_window(self, cr, uid, activity_id, fields, context=None):
        return {}

    @data_model_event(callback="cancel_act_window")
    def cancel_act_window(self, cr, uid, activity_id, fields, context=None):
        return {}

    @data_model_event(callback="update_activity")
    def update_activity(self, cr, uid, activity_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}

    @data_model_event(callback="submit")
    def submit(self, cr, uid, activity_id, vals, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        assert isinstance(vals, dict), "vals must be a dict, found to be %s" % type(vals)
        return {}

    @data_model_event(callback="retrieve")
    def retrieve(self, cr, uid, activity_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}


    @data_model_event(callback="validate")
    def validate(self, cr, uid, activity_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}

    # MGMT API
    @data_model_event(callback="schedule")
    def schedule(self, cr, uid, activity_id, date_scheduled=None, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        if date_scheduled:
            date_formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d %H', '%Y-%m-%d']
            res = []
            for df in date_formats:
                try:
                    dt.strptime(date_scheduled, df)
                except:
                    res.append(False)
                else:
                    res.append(True)
                    #assert any(res), "date_scheduled must be one of the following types: %s. Found: %s" % (date_formats, date_scheduled)
        return {}

    @data_model_event(callback="assign")
    def assign(self, cr, uid, activity_id, user_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        assert isinstance(user_id, (int, long)), "user_id must be int or long, found to be %s" % type(user_id)
        return {}

    @data_model_event(callback="unassign")
    def unassign(self, cr, uid, activity_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}

    @data_model_event(callback="start")
    def start(self, cr, uid, activity_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}

    @data_model_event(callback="complete")
    def complete(self, cr, uid, activity_id, context=None):
        if isinstance(activity_id, list) and len(activity_id) == 1:
            activity_id = activity_id[0]
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}

    @data_model_event(callback="cancel")
    def cancel(self, cr, uid, activity_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}

    @data_model_event(callback="abort")
    def abort(self, cr, uid, activity_id, context=None):
        assert isinstance(activity_id, (int, long)), "activity_id must be int or long, found to be %s" % type(
            activity_id)
        return {}


class nh_activity_data(orm.AbstractModel):
    _name = 'nh.activity.data'
    _transitions = {
        'new': ['schedule', 'plan', 'start', 'complete', 'cancel', 'submit', 'assign', 'unassign', 'retrieve',
                'validate'],
        'planned': ['schedule', 'start', 'complete', 'cancel', 'submit', 'assign', 'unassign', 'retrieve', 'validate'],
        'scheduled': ['start', 'complete', 'cancel', 'submit', 'assign', 'unassign', 'retrieve', 'validate'],
        'started': ['complete', 'cancel', 'submit', 'assign', 'unassign', 'retrieve', 'validate'],
        'completed': ['retrieve', 'validate', 'cancel'],
        'cancelled': ['retrieve', 'validate']
    }
    _description = _name #"Activity Data Base Model"
    _start_view_xmlid = None
    _schedule_view_xmlid = None
    _submit_view_xmlid = None
    _complete_view_xmlid = None
    _cancel_view_xmlid = None
    _form_description = None
    
#     _handlers = [
#         {'handler_model': _name, 
#          'handler_method': 'handler_complete', 
#          'trigger_model': _name, 
#          'trigger_method': 'complete'},
#                  
#         {'handler_model': _name, 
#          'handler_method': 'handler_create_activity', 
#          'trigger_model': 'nh.clinical.patient.move', 
#          'trigger_method': 'complete'},
#     ]
#     
#     def handler_complete(self, cr, uid, event):
#         print "Handler Conplete"
#         
#     def handler_create_activity(self, cr, uid, event):
#         print "Handler Create Activity"
            
    def is_action_allowed(self, state, action):
        return action in self._transitions[state]
    
    _columns = {
        'name': fields.char('Name', size=256),
        'activity_id': fields.many2one('nh.activity', "activity"),
        'date_started': fields.related('activity_id', 'date_started', string='Start Time', type='datetime'),
        'date_terminated': fields.related('activity_id', 'date_terminated', string='Terminated Time', type='datetime'),
        'state': fields.related('activity_id', 'state', type='char', string='State', size=64),
        'terminate_uid': fields.related('activity_id', 'terminate_uid', string='Completed By', type='many2one', relation='res.users')
    }

    _order = 'id desc'


    def handle_ews_complete(self, crr, uid, event): # test. to be removed
        print "handle_ews_complete event: %s" % event
        
    def create(self, cr, uid, vals, context=None):
        rec_id = super(nh_activity_data, self).create(cr, uid, vals, context)
        return rec_id

    def create_activity(self, cr, uid, vals_activity={}, vals_data={}, context=None):
        assert isinstance(vals_activity, dict), "vals_activity must be a dict, found %" % type(vals_activity)
        assert isinstance(vals_data, dict), "vals_data must be a dict, found %" % type(vals_data)
        activity_pool = self.pool['nh.activity']
        vals_activity.update({'data_model': self._name})
        new_activity_id = activity_pool.create(cr, uid, vals_activity, context)
        vals_data and activity_pool.submit(cr, uid, new_activity_id, vals_data, context)

        return new_activity_id

    def submit_ui(self, cr, uid, ids, context=None):
        if context.get('active_id'):
            activity_pool = self.pool['nh.activity']
            activity_pool.write(cr, uid, context['active_id'], {'data_ref': "%s,%s" % (self._name, str(ids[0]))})
            activity = activity_pool.browse(cr, uid, context['active_id'], context)
            activity_pool.update_activity(cr, SUPERUSER_ID, activity.id, context)
            _logger.debug("activity '%s', activity.id=%s data submitted via UI" % (activity.data_model, activity.id))
        return {'type': 'ir.actions.act_window_close'}

    def complete_ui(self, cr, uid, ids, context=None):
        if context.get('active_id'):
            active_id = context['active_id']
            activity_pool = self.pool['nh.activity']
            activity_pool.write(cr, uid, active_id, {'data_ref': "%s,%s" % (self._name, str(ids[0]))})
            activity = activity_pool.browse(cr, uid, active_id, context)
            activity_pool.update_activity(cr, SUPERUSER_ID, activity.id, context)
            activity_pool.complete(cr, uid, activity.id, context)
            _logger.debug("activity '%s', activity.id=%s data completed via UI" % (activity.data_model, activity.id))
        return {'type': 'ir.actions.act_window_close'}

    def start_act_window(self, cr, uid, activity_id, context=None):
        return self.act_window(cr, uid, activity_id, "start", context)

    def schedule_act_window(self, cr, uid, activity_id, context=None):
        return self.act_window(cr, uid, activity_id, "schedule", context)

    def submit_act_window(self, cr, uid, activity_id, context=None):
        return self.act_window(cr, uid, activity_id, "submit", context)

    def complete_act_window(self, cr, uid, activity_id, context=None):
        return self.act_window(cr, uid, activity_id, "complete", context)

    def cancel_act_window(self, cr, uid, activity_id, context=None):
        return self.act_window(cr, uid, activity_id, "cancel", context)


    def act_window(self, cr, uid, activity_id, command, context=None):
        activity_id = isinstance(activity_id, (list, tuple)) and activity_id[0] or activity_id      
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)        
        imd_pool = self.pool['ir.model.data']
        model_xmlid = "model_%s" % activity.data_ref._name.replace(".","_")
        model_id = imd_pool.search(cr, uid, [['name','=',model_xmlid]])
        except_if(not model_id, msg="Model with xmlid %s is not found in ir.model.data" % model_xmlid)
        model_id = model_id[0]
        model_imd = imd_pool.browse(cr, uid, model_id)
        view_xmlid = eval("activity.data_ref._%s_view_xmlid" % command)
        view = imd_pool.get_object(cr, uid, model_imd.module, view_xmlid, context)
        except_if(not view, msg="View with xmlid='%s' not found" % view_xmlid)
        ctx = context or {}
        ctx.update({'nh_source': 'nh.activity'})
        aw = {
            'type': 'ir.actions.act_window',
            'view_id': view.id,
            'res_model': view.model,
            'res_id': activity.data_ref.id,
            'view_type': view.type,
            'view_mode': view.type,
            'target': "new",
            'context': ctx,
            'name': view.name
        }
        return aw


    def validate(self, cr, uid, activity_id, context=None):
        return {}

    def start(self, cr, uid, activity_id, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        except_if(not self.is_action_allowed(activity.state, 'start'),
                  msg="activity of type '%s' can not be started from state '%s'" % (
                  activity.data_model, activity.state))
        activity_pool.write(cr, uid, activity_id, {'state': 'started', 'date_started': dt.now().strftime(DTF)}, context)
        _logger.debug("activity '%s', activity.id=%s started" % (activity.data_model, activity.id))
        return {}

    def complete(self, cr, uid, activity_id, context=None):
        if isinstance(activity_id, list) and len(activity_id) == 1:
            activity_id = activity_id[0]
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        except_if(not self.is_action_allowed(activity.state, 'complete'),
                  msg="activity of type '%s' can not be completed from state '%s'" % (
                  activity.data_model, activity.state))
        now = dt.today().strftime('%Y-%m-%d %H:%M:%S')
        activity_pool.write(cr, uid, activity.id, 
                            {'state': 'completed', 'terminate_uid':uid,
                             'date_terminated': now}, context)
        _logger.debug("activity '%s', activity.id=%s completed" % (activity.data_model, activity.id))
        return {}

    def assign(self, cr, uid, activity_id, user_id, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        except_if(not self.is_action_allowed(activity.state, 'assign'),
                  msg="activity of type '%s' can not be assigned in state '%s'" % (activity.data_model, activity.state))
        except_if(activity.user_id, msg="activity is assigned already assigned to %s!" % activity.user_id.name)
        activity_vals = {'user_id': user_id}
        activity_pool.write(cr, uid, activity_id, activity_vals)
        _logger.debug("activity '%s', activity.id=%s assigned to user.id=%s" % (activity.data_model, activity.id, user_id))
        return {}

    def unassign(self, cr, uid, activity_id, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        except_if(not self.is_action_allowed(activity.state, 'unassign'),
                  msg="activity of type '%s' can not be unassigned in state '%s'" % (
                  activity.data_model, activity.state))
        except_if(not activity.user_id, msg="activity is not assigned yet!")
        activity_pool.write(cr, uid, activity_id, {'user_id': False}, context)
        _logger.debug("activity '%s', activity.id=%s unassigned" % (activity.data_model, activity.id))
        return {}

    def abort(self, cr, uid, activity_id, context=None):
        return {}

    def cancel(self, cr, uid, activity_id, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        except_if(not self.is_action_allowed(activity.state, 'cancel'),
                  msg="activity of type '%s' can not be cancelled in state '%s'" % (
                  activity.data_model, activity.state))
        now = dt.today().strftime('%Y-%m-%d %H:%M:%S')
        activity_pool.write(cr, uid, activity_id, {'state': 'cancelled', 
                            'terminate_uid': uid, 'date_terminated': now}, context)
        _logger.debug("activity '%s', activity.id=%s cancelled" % (activity.data_model, activity.id))
        return {}

    def retrieve(self, cr, uid, activity_id, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        except_if(not self.is_action_allowed(activity.state, 'retrieve'),
                  msg="Data can't be retrieved from activity of type '%s' in state '%s'" % (
                  activity.data_model, activity.state))
        return self.retrieve_read(cr, uid, activity_id, context=None)


    def retrieve_read(self, cr, uid, activity_id, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        model_pool = self.pool[activity.data_model]
        return model_pool.read(cr, uid, activity.data_ref.id, [], context)


    def retrieve_browse(self, cr, uid, activity_id, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        return activity.data_ref

    def schedule(self, cr, uid, activity_id, date_scheduled=None, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context=None)
        except_if(not self.is_action_allowed(activity.state, 'schedule'),
                  msg="activity of type '%s' can't be scheduled in state '%s'" % (activity.data_model, activity.state))
        except_if(not activity.date_scheduled and not date_scheduled,
                  msg="Scheduled date is neither set on activity nor passed to the method")
        date_scheduled = date_scheduled or activity.date_scheduled
        activity_pool.write(cr, uid, activity_id, {'date_scheduled': date_scheduled, 'state': 'scheduled'}, context)
        _logger.debug("activity '%s', activity.id=%s scheduled, date_scheduled='%s'" % (
        activity.data_model, activity.id, date_scheduled))
        return {}

    def submit(self, cr, uid, activity_id, vals, context=None):
        activity_pool = self.pool['nh.activity']
        activity = activity_pool.browse(cr, uid, activity_id, context)
        except_if(not self.is_action_allowed(activity.state, 'submit'),
                  msg="Data can't be submitted to activity of type '%s' in state '%s'" % (
                  activity.data_model, activity.state))
        data_vals = vals.copy()

        if not activity.data_ref:
            _logger.debug(
                "activity '%s', activity.id=%s data submitted: %s" % (activity.data_model, activity.id, str(data_vals)))
            data_vals.update({'activity_id': activity_id})
            data_id = self.create(cr, uid, data_vals, context)
            activity_pool.write(cr, uid, activity_id, {'data_ref': "%s,%s" % (self._name, data_id)})
        else:
            _logger.debug(
                "activity '%s', activity.id=%s data submitted: %s" % (activity.data_model, activity.id, str(vals)))
            self.write(cr, uid, activity.data_ref.id, vals, context)

        self.update_activity(cr, SUPERUSER_ID, activity_id, context)
        return {}

    def update_activity(self, cr, uid, activity_id, context=None):
        """
            Hook for data-driven activity update
            Should be called on methods that change activity data
        """
        return {}

