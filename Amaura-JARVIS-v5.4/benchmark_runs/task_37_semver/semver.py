class SemVer:
    def __init__(self, version_str: str):
        parts = version_str.split('.')
        if len(parts) != 3:
            raise ValueError("Version string must be in format 'major.minor.patch'")
        
        self.major = int(parts[0])
        self.minor = int(parts[1])
        self.patch = int(parts[2])

    def __eq__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return (self.major == other.major and
                self.minor == other.minor and
                self.patch == other.patch)

    def __lt__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        return self.patch < other.patch

    def __gt__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        if self.major != other.major:
            return self.major > other.major
        if self.minor != other.minor:
            return self.minor > other.minor
        return self.patch > other.patch

    def __repr__(self):
        return f"SemVer('{self.major}.{self.minor}.{self.patch}')"