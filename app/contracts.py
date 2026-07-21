from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TransformDSL(str, Enum):
    DIRECT = "DIRECT"
    CAST = "CAST"
    SHA256 = "SHA256"
    TO_TIMESTAMP = "TO_TIMESTAMP"
    LITERAL = "LITERAL"
    TRIM = "TRIM"
    DEFAULT = "DEFAULT"


class ValueStreamContract(BaseModel):
    domain: str = Field(description="Business domain name")
    entity_name: str = Field(description="Target entity name")
    business_keys: List[str] = Field(
        default_factory=list, description="Primary business key column names"
    )


class BronzeColumnContract(BaseModel):
    name: str
    type: str
    sample_values: Optional[List[Any]] = None


class BronzeSchemaContract(BaseModel):
    entity_name: str
    columns: List[BronzeColumnContract]


class ConformedAttributeContract(BaseModel):
    source_column: str
    target_attribute: str
    description: Optional[str] = ""
    confidence_score: Optional[float] = 1.0


class ConformedTableContract(BaseModel):
    source_table: str
    subject_area: str
    target_table: str
    attributes: List[ConformedAttributeContract]


class SilverConformedContract(BaseModel):
    silver_conformed_tables: List[ConformedTableContract]


class MappingItemContract(BaseModel):
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    transformation_rule: str
    transform_dsl: TransformDSL = TransformDSL.DIRECT
    is_surrogate_key: bool = False


class MappingMatrixContract(BaseModel):
    mappings: List[MappingItemContract]


class DABBundleContract(BaseModel):
    bundle_name: str
    files: Dict[str, str]
