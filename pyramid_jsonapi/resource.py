from dataclasses import (
    dataclass,
)

__all__ = (
    'ResourceIndicator',
)


@dataclass(eq=True, frozen=True)
class ResourceIndicator:
    type: str
    id: str

    @classmethod
    def from_dict(cls, dict_):
        return cls(dict_['type'], dict_['id'])

    def to_dict(self):
        if self.id:
            return {'type': self.type, 'id': self.id}
        else:
            return None
