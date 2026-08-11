import inspect
import unittest
from jarvis.amaura.commands import Command
from jarvis.amaura.control_plane import AmauraControlPlane

class TestAmauraCommands(unittest.TestCase):
    def test_command_handlers_match_contract(self):
        control = AmauraControlPlane(":memory:")
        try:
            for cls in Command.__subclasses__():
                domain = cls.domain
                handler_name = cls.handler
                if domain == "control_plane":
                    handler_obj = control
                elif domain == "acquisition":
                    handler_obj = control.acquisition
                elif domain == "content_factory":
                    handler_obj = control.content_factory
                else:
                    self.fail(f"Unknown domain {domain} for command {cls.__name__}")
                
                handler = getattr(handler_obj, handler_name, None)
                self.assertIsNotNone(handler, f"Handler {handler_name} not found on {domain} for {cls.__name__}")
                
                sig = inspect.signature(handler)
                
                # Get the keys as they would be output by model_dump(by_alias=True)
                model_fields = set()
                for name, field in cls.model_fields.items():
                    if name in ("domain", "handler"):
                        continue
                    model_fields.add(field.alias if field.alias else name)
                
                sig_params = set(sig.parameters.keys())
                sig_params.discard("self")
                
                self.assertEqual(model_fields, sig_params, f"Signature mismatch for {cls.__name__}")
        finally:
            control.close()

if __name__ == '__main__':
    unittest.main()
