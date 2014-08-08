# -*- encoding: utf-8 -*-
from openerp.osv import orm, fields, osv
import logging        
from pprint import pprint as pp
_logger = logging.getLogger(__name__)

from faker import Faker
fake = Faker()


class Demo(object):
    """
    Demo decorator class.
    Current usage:
    from openerp.addons.t4demo.demo import Demo 
    @Demo
    class my_model_class(orm.Model):
        ....
    
    To activate demo data generation for create and write the following to be done:
        - define method to provide demo values using signature: 
            demo_values(*args, **kwrags)
                - reuired args: self, cr, uid
                - required kwargs: values={}
                other args, kwargs are optional and will be handled correctly
        - pass in the context 
            - 'demo': True to provide missing values for create, write with demo values
            - 'demo_args':[], 'demo_kwargs':{} to provide additional arguments for your demo values method
    
    Functionality:
        If in the current python model create, write method exist, they are decorated to receive demo_values
        If any of the methods are absent, local place holders are added and then decorated
    
    Target for improvement:
        if module is installed:
            1st stage: all models to receive create and write decorators
            2nd stage: models to receive decorators to be listed (preferably in the configuration)
            
    Some explanations on __call__, create, write, odoo MRO (Method Resolution Order), demo methods/attributes
        - Unlike python classes, odoo classes have the following MRO: class orm.Model, class python class, ..., Model, BaseModel, object, type 
            example for res.users: orm.model.res.user, res_users_local, ... 
        - __call__ makes class-to-class (not object) methods insertion, decoration
        - create, write place holders to be inserted in the decorated class in case of methods absence. 
            Call for the parent method is using self.__class__.mro()[1] due to self.class is orm.model... according to odoo MRO
        - @Demo decorator also inserts attributes self._fake, self._seed from package fake-factory
            and method next_seed_fake(self, seed=None) returning self._fake with passed seed or incremented self._seed
        
    """    
    def __init__(self):
        self._fake = fake
        self._seed = self._fake.random_int(min=1000001, max=9999999)
        
    def next_seed_fake(self, seed=None):
        if seed:
            self._fake.seed(seed)
        else:
            self._seed += 1
            self._fake.seed(self._seed)
        return self._fake
    
        
    def demo_get_values(self, cr, uid, values={}, context=None):
        context = context or {}
        res = values
        if context.get('demo'):
            method = context.get('demo_method', 'demo_values')
            except_if(not hasattr(self, method), msg="Method %s() is not implemented for model '%s'" % (method, self._name))
            args = context.get('demo_args', [])
            kwargs = context.get('demo_kwargs', {})
            kwargs.update({'values': values.copy()})
            code = "self.%s(cr, uid, *args, **kwargs)" % method
            _logger.info("_get_values code: %s" % code)
            _logger.info("_get_values args: %s, kwargs: %s" % (args, kwargs))
            fake_values = eval(code)
            context.pop('demo')
            context.get('demo_args') and context.pop('demo_args')
            context.get('demo_kwargs') and context.pop('demo_kwargs')
            context.get('demo_method') and context.pop('demo_method')
            res = fake_values
        return res
    
    @staticmethod
    def demo_values_decorator(func):
        def wrapper(*args, **kwargs):
            if func.__name__ == 'create':
                self, cr, uid, values = args[:4]
                context = len(args) > 4 and args[4] or kwargs.values() and kwargs.values()[0] or None
                
            elif func.__name__ == 'write':
                self, cr, uid, ids, values = args[:5]
                context = len(args) > 5 and args[5] or kwargs.values() and kwargs.values()[0] or None               
            else:
                print "Unexpected function name.... RETURN"
                return
            v = values
            if context and context.get('demo'):
                method = context.get('demo_method', 'demo_values')
                if not hasattr(self, method):
                    raise orm.except_orm("Not Implemented", "Method %s() is not implemented for model '%s'" % (method, self._name))
                demo_args = context.get('demo_args', [])
                demo_kwargs = context.get('demo_kwargs', {})
                demo_kwargs.update({'values': values.copy()})
                code = "self.%s(cr, uid, *demo_args, **demo_kwargs)" % method
                #FIXME should we clean it up???
                context.pop('demo')
                context.get('demo_args') and context.pop('demo_args')
                context.get('demo_kwargs') and context.pop('demo_kwargs')
                context.get('demo_method') and context.pop('demo_method')
                v = eval(code)
                _logger.info("Demo mode values to be applied: %s" % v)
            try:
                print "Entering Decorated: [%s]" % (func.__name__)
                try:
                    if func.__name__ == 'create':
                        return func(self, cr, uid, v, context)
                    elif func.__name__ == 'write':
                        return func(self, cr, uid, ids, v, context)
                except Exception, e:
                    print 'Exception in Decorated %s : %s' % (func.__name__, e)
            finally:
                print "Exiting Decorated: [%s]" % func.__name__
        return wrapper        
        
    
    def create(self, cr, uid, values, context=None):
        #import pdb; pdb.set_trace()
        print "ADDED CREATE..."
        res = super(self.__class__.mro()[1], self).create(cr, uid, values, context)
        return res

    def write(self, cr, uid, ids, values, context=None):
        #import pdb; pdb.set_trace()
        print "ADDED WRITE..."
        res = super(self.__class__.mro()[1], self).write(cr, uid, ids, values, context)
        return res
     
    def __call__(self, cls):
        cls._fake = fake
        cls._seed = self._fake.random_int(min=1000001, max=9999999)
        cls.next_seed_fake = self.__class__.__dict__['next_seed_fake']
        
        if 'create' not in cls.__dict__:
            cls.create = self.__class__.__dict__['create']
        setattr(cls, 'create', self.demo_values_decorator(cls.create))
        if 'write' not in cls.__dict__:
            cls.write = self.__class__.__dict__['write']
        setattr(cls, 'write', self.demo_values_decorator(cls.write))
        #import pdb; pdb.set_trace()
        return cls