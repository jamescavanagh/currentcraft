"""Exact physical quantities and unparsed money. No implicit conversions."""
from decimal import Decimal, localcontext
import re
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from .facts import Fact, unknown
from .identity import Text

DECIMAL_TEXT = (r"(?:\+?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
                r"|-(?:0+(?:\.0*)?|\.0+))(?:[eE][+-]?[0-9]+)?")


class UnitRef(BaseModel):
    """Versioned reference to a unit in an explicitly selected dictionary."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    dictionary_id: Text
    dictionary_version: Text
    code: Text
    dimension: Text


class Quantity(BaseModel):
    """Finite nonnegative Decimal and explicit unit; zero remains zero."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    amount: Decimal = Field(ge=0, allow_inf_nan=False)
    unit: UnitRef

    @field_validator("amount", mode="before")
    @classmethod
    def exact_input(cls, value, info: ValidationInfo):
        if info.mode == "json" and not isinstance(value, str):
            raise ValueError("JSON quantities require exact decimal strings, not JSON numbers")
        if isinstance(value, (float, bool)):
            raise ValueError("use Decimal, integer or source decimal text, never float/bool")
        if isinstance(value, str) and re.fullmatch(DECIMAL_TEXT, value) is None:
            raise ValueError("quantity text must be canonical finite nonnegative decimal text")
        if not isinstance(value, (str, int, Decimal)):
            raise ValueError("quantity input must be Decimal, integer or decimal text")
        return value

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema["properties"]["amount"] = {
            "title": "Amount", "type": "string", "minLength": 1,
            "pattern": "^(?:" + DECIMAL_TEXT + ")$", "not": {"pattern": r"\s"},
            "description": "Wire format: exact finite nonnegative decimal string. Python also accepts Decimal/int; JSON numbers are rejected."
        }
        return schema

    def plus(self, other: "Quantity") -> "Quantity":
        if self.unit != other.unit:
            raise ValueError("unit references differ; conversion is not defined")
        # Do not round source quantities to the ambient Decimal context precision.
        precision = max(self.amount.adjusted(), other.amount.adjusted()) - min(
            self.amount.as_tuple().exponent, other.amount.as_tuple().exponent) + 2
        with localcontext() as context:
            context.prec = max(context.prec, precision)
            total = self.amount + other.amount
        return Quantity(amount=total, unit=self.unit)


class SourceMoney(BaseModel):
    """Source money text with available context. No parsing or formatting."""
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    text: Fact[Text]
    currency: Fact[Text] = Field(default_factory=unknown)
    context: Fact[Text] = Field(default_factory=unknown)
