"""IC4 model-specific trigger semantics; missing properties are not generic defaults."""
from .trigger import configure_external_trigger


# This model has one physical TRIGGER_IN, not a selectable TriggerSource node.
# Manufacturer technical reference manual v1.2, sections 5.4 and 5.5:
# https://s1-dl.theimagingsource.com/api/2.5/packages/documentation/manual-trm/trmdmk37bux250/84de9312-94ca-511a-862b-6f183b4ecdc4/trmdmk37bux250.en_US.pdf
FIXED_INPUT_MODELS = {"DMK 37BUX250": "TRIGGER_IN"}


def configure_ic4_trigger(sdk, props, model, source):
    fixed_input = None
    try:
        props.find_enumeration("TriggerSource")
    except Exception as exc:
        # A missing node on a documented fixed-input model is expected. Do not
        # hide locked nodes, driver failures, or missing nodes on unknown models.
        if getattr(exc, "code", None) != sdk.ErrorCode.GenICamFeatureNotFound:
            raise
        fixed_input = FIXED_INPUT_MODELS.get(model)
        if fixed_input is None:
            raise RuntimeError(
                f"{model} does not expose a selectable trigger input, and its fixed-input "
                "configuration has not been added to BURST. Recording has not started."
            ) from exc
    configured = configure_external_trigger(
        lambda name: props.find_enumeration(name).value,
        lambda name, value: setattr(props.find_enumeration(name), "value", value), source,
        choices=lambda: [entry.name for entry in props.find_enumeration("TriggerSource").entries],
        fixed_input=fixed_input,
    )
    # Keep documented physical wiring separate from actual property readback.
    input_info = {"name": fixed_input or configured["TriggerSource"],
                  "selection": "fixed_by_camera_model" if fixed_input else "camera_property"}
    return configured, input_info
