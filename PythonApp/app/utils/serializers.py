from typing import Type, List, TypeVar

T = TypeVar("T")

def serialize_list(items: List, schema_class: Type[T]) -> List[T]:
    return [schema_class.from_orm(item) for item in items]
