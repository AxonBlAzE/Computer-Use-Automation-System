"""The versioned, declarative capability contract. No executable artifact code."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StringField(Model):
    type: Literal["string"] = "string"
    description: str
    min_length: int = Field(default=1, ge=0)
    max_length: int = Field(default=200, ge=1, le=2000)
    choices: list[str] | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.min_length > self.max_length:
            raise ValueError("min_length exceeds max_length")
        return self

    def accepts(self, value: object) -> bool:
        return (
            isinstance(value, str)
            and self.min_length <= len(value) <= self.max_length
            and (self.choices is None or value in self.choices)
        )


class InputRef(Model):
    source: Literal["input"]
    name: str


class Constant(Model):
    source: Literal["literal"]
    value: str


Value = Annotated[InputRef | Constant, Field(discriminator="source")]


class Target(Model):
    role: Literal["textbox", "button", "combobox", "heading", "status", "alert"]
    name: str = Field(min_length=1)


class Navigate(Model):
    action: Literal["navigate"]
    id: str
    path: str


class Fill(Model):
    action: Literal["fill"]
    id: str
    target: Target
    value: Value


class Select(Model):
    action: Literal["select"]
    id: str
    target: Target
    value: Value


class Click(Model):
    action: Literal["click"]
    id: str
    target: Target


class Check(Model):
    action: Literal["check"]
    id: str
    target: Target
    equals: Value | None = None


Step = Annotated[Navigate | Fill | Select | Click | Check, Field(discriminator="action")]


class Outcome(Model):
    code: str
    after_step: str
    target: Target


class Output(Model):
    field: StringField
    target: Target


class Capability(Model):
    schema_version: Literal["1.0"]
    name: str
    version: str
    description: str
    inputs: dict[str, StringField]
    outputs: dict[str, Output]
    steps: list[Step] = Field(min_length=1, max_length=100)
    outcomes: list[Outcome] = Field(default_factory=list)
    success: Check

    @model_validator(mode="after")
    def references_are_valid(self):
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step IDs must be unique")
        for step in [*self.steps, self.success]:
            value = getattr(step, "value", None) or getattr(step, "equals", None)
            if isinstance(value, InputRef) and value.name not in self.inputs:
                raise ValueError("unknown input reference")
        if any(outcome.after_step not in ids for outcome in self.outcomes):
            raise ValueError("outcome references an unknown step")
        codes = [outcome.code for outcome in self.outcomes]
        if len(codes) != len(set(codes)):
            raise ValueError("outcome codes must be unique")
        return self

    def validate_inputs(self, values: dict[str, object]) -> None:
        if values.keys() != self.inputs.keys():
            raise ValueError("input names do not match capability contract")
        if any(not field.accepts(values[name]) for name, field in self.inputs.items()):
            raise ValueError("input value violates capability contract")


class Success(Model):
    status: Literal["success"] = "success"
    outputs: dict[str, str]


class BusinessOutcome(Model):
    status: Literal["business_outcome"] = "business_outcome"
    code: str
    step: str


class Failure(Model):
    status: Literal["failure"] = "failure"
    code: str
    step: str | None
    expected: str
    observed: str


RunResult = Success | BusinessOutcome | Failure
