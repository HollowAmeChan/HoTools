"""Regression checks for the Humanoid property to Unity humanName export."""

from Exporter.HumanoidMappingExporter import HumanoidMappingExporter


def test_hand_and_finger_human_names():
    convert = HumanoidMappingExporter.to_unity_human_name

    assert convert("hand.L") == "LeftHand"
    assert convert("hand.R") == "RightHand"
    assert convert("thumb_proximal.R") == "Right Thumb Proximal"
    assert convert("index_intermediate.L") == "Left Index Intermediate"
    assert convert("middle_distal.R") == "Right Middle Distal"
