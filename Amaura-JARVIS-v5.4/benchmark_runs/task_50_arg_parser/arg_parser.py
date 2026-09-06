class ArgumentParser:
    def __init__(self, description: str = ""):
        self.description = description
        self.arguments = {}
        
    def add_argument(self, name: str, type_: type = str, help: str = "", required: bool = False):
        self.arguments[name] = {
            "type": type_,
            "help": help,
            "required": required
        }
        
    def parse_args(self, argv: list[str]) -> dict:
        args = {}
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg.startswith("-"):
                arg_name = arg.lstrip("-")
                if arg_name not in self.arguments:
                    raise ValueError(f"Unknown argument: {arg_name}")
                
                if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                    if self.arguments[arg_name]["required"]:
                        raise ValueError(f"Argument {arg_name} is required")
                    args[arg_name] = None
                else:
                    try:
                        args[arg_name] = self.arguments[arg_name]["type"](argv[i + 1])
                    except ValueError:
                        raise ValueError(f"Invalid value for argument {arg_name}")
                    i += 1
            i += 1
        
        for arg_name, arg_info in self.arguments.items():
            if arg_info["required"] and arg_name not in args:
                raise ValueError(f"Missing required argument: {arg_name}")
        
        return args
