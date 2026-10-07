from types import SimpleNamespace
from unittest.mock import MagicMock

from aifa_pyrit.crescendo_step_capture import CrescendoMemoryTracer, message_role, message_text
from aifa_pyrit.pyrit_runner import PyRITRunner


def test_message_helpers_with_message_pieces():
    piece = SimpleNamespace(converted_value="Converted text", original_value="Original text", role="user", api_role="user")
    msg = SimpleNamespace(message_pieces=[piece], api_role="user")

    assert message_text(msg) == "Converted text"
    assert message_role(msg) == "user"


def test_message_helpers_fallback_to_original_value():
    piece = SimpleNamespace(converted_value="", original_value="Fallback original", role="assistant")
    msg = SimpleNamespace(message_pieces=[piece])

    assert message_text(msg) == "Fallback original"
    assert message_role(msg) == "assistant"


def test_message_helpers_flat_object():
    flat_msg = SimpleNamespace(converted_value="Flat converted", role="user")

    assert message_text(flat_msg) == "Flat converted"
    assert message_role(flat_msg) == "user"


def test_extract_turn_pairs_with_message_pieces():
    user_piece_1 = SimpleNamespace(converted_value="Turn 1 prompt", original_value="", role="user", api_role="user")
    asst_piece_1 = SimpleNamespace(converted_value="Turn 1 response", original_value="", role="assistant", api_role="assistant")
    user_piece_2 = SimpleNamespace(converted_value="Turn 2 prompt", original_value="", role="user", api_role="user")
    asst_piece_2 = SimpleNamespace(converted_value="Turn 2 response", original_value="", role="assistant", api_role="assistant")

    messages = [
        SimpleNamespace(message_pieces=[user_piece_1], api_role="user"),
        SimpleNamespace(message_pieces=[asst_piece_1], api_role="assistant"),
        SimpleNamespace(message_pieces=[user_piece_2], api_role="user"),
        SimpleNamespace(message_pieces=[asst_piece_2], api_role="assistant"),
    ]

    turns = PyRITRunner._extract_turn_pairs(messages, outcome="success")

    assert len(turns) == 2
    assert turns[0]["prompt"] == "Turn 1 prompt"
    assert turns[0]["response"] == "Turn 1 response"
    assert turns[0]["outcome"] == "success"
    assert turns[1]["prompt"] == "Turn 2 prompt"
    assert turns[1]["response"] == "Turn 2 response"
    assert turns[1]["outcome"] == "success"


def test_crescendo_memory_tracer_capture_escalation_chain():
    user_piece = SimpleNamespace(converted_value="Escalation step prompt", original_value="", role="user", api_role="user")
    asst_piece = SimpleNamespace(converted_value="Escalation step response", original_value="", role="assistant", api_role="assistant")

    messages = [
        SimpleNamespace(message_pieces=[user_piece], api_role="user"),
        SimpleNamespace(message_pieces=[asst_piece], api_role="assistant"),
    ]

    mock_memory = MagicMock()
    mock_memory.get_conversation.return_value = messages

    tracer = CrescendoMemoryTracer(memory=mock_memory)
    escalations = tracer.capture_escalation_chain(conversation_id="test_conv_id")

    assert len(escalations) == 1
    assert escalations[0]["escalation_step"] == 1
    assert escalations[0]["prompt"] == "Escalation step prompt"
    assert escalations[0]["response"] == "Escalation step response"


def test_build_turns_prioritizes_objective_turns():
    runner = PyRITRunner()

    result = SimpleNamespace(
        executed_turns=1,
        outcome="success",
        conversation_id="obj_conv_123",
        adversarial_chat_conversation_ids=["adv_conv_456"],
    )

    mock_memory = MagicMock()
    obj_turns = [{"prompt": "Actual user prompt", "response": "Target reply", "outcome": "success"}]
    adv_turns = [{"prompt": "Internal attacker prompt", "response": "Internal attacker reply", "outcome": "success"}]

    runner._try_extract_objective_turns = MagicMock(return_value=obj_turns)
    runner._try_extract_adversarial_turns = MagicMock(return_value=adv_turns)

    turns = runner._build_turns_from_result(result, memory=mock_memory)

    assert turns == obj_turns
    runner._try_extract_objective_turns.assert_called_once_with(mock_memory, "obj_conv_123", 1, "success")
    runner._try_extract_adversarial_turns.assert_not_called()
