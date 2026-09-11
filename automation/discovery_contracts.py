"""Task intent is supplied by a caller; the model discovers the action sequence."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from automation.contracts import Model, Step, StringField, Target, Value


class OutputGoal(Model):
    field: StringField
    equals: Value


class OutcomeRule(Model):
    code: str
    after_click: Target
    target: Target


class DiscoveryTask(Model):
    name: str
    version: str = "1.0.0"
    goal: str
    entry_path: str = "/"
    inputs: dict[str, StringField]
    outputs: dict[str, OutputGoal]
    success_output: str
    outcome_rules: list[OutcomeRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_contract(self):
        if self.success_output not in self.outputs:
            raise ValueError("success output must be declared")
        for output in self.outputs.values():
            value = output.equals
            if value.source == "input" and value.name not in self.inputs:
                raise ValueError("unknown output input reference")
        codes = [rule.code for rule in self.outcome_rules]
        if len(codes) != len(set(codes)):
            raise ValueError("outcome codes must be unique")
        return self

    def validate_inputs(self, inputs: dict[str, object]):
        if inputs.keys() != self.inputs.keys():
            raise ValueError("incorrect input names")
        if any(not field.accepts(inputs[name]) for name, field in self.inputs.items()):
            raise ValueError("incorrect input values")


class Act(Model):
    kind: Literal["act"]
    intent: Literal["enter_input", "advance", "verify"]
    step: Step


class Finish(Model):
    kind: Literal["finish"]
    intent: Literal["finish"]
    outputs: dict[str, Target]


Decision = Annotated[Act | Finish, Field(discriminator="kind")]


class DecisionEnvelope(Model):
    decision: Decision
