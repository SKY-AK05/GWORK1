try:
    from mmengine.registry import Registry
except ImportError:
    class Registry:
        def __init__(self, name, **kwargs):
            self.name = name
            self.kwargs = kwargs
            self.module_dict = {}

        def register_module(self, force=False):
            def decorator(obj):
                key = getattr(obj, "__name__", str(obj))
                if not force and key in self.module_dict:
                    raise KeyError(f"{key} is already registered in {self.name}")
                self.module_dict[key] = obj
                return obj

            return decorator

TOOL = Registry("tool", locations=["src.tool"])
