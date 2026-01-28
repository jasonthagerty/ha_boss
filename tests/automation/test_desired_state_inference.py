"""Tests for desired state inference service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.automation.desired_state_inference import DesiredStateInference, InferredState
from ha_boss.core.database import AutomationDesiredState
from ha_boss.intelligence.llm_router import TaskComplexity


@pytest.fixture
def mock_llm_router():
    """Create mock LLM router."""
    router = AsyncMock()
    router.generate = AsyncMock()
    return router


@pytest.fixture
def mock_database():
    """Create mock database."""
    db = MagicMock()
    db.async_session = MagicMock()
    return db


@pytest.fixture
def inference_service(mock_llm_router, mock_database):
    """Create DesiredStateInference service with mocks."""
    return DesiredStateInference(
        llm_router=mock_llm_router,
        database=mock_database,
        instance_id="test_instance",
    )


class TestDesiredStateInference:
    """Test DesiredStateInference service."""

    @pytest.mark.asyncio
    async def test_infer_light_turn_on(self, inference_service, mock_llm_router):
        """Test inference for light.turn_on action."""
        automation_config = {
            "action": [
                {
                    "service": "light.turn_on",
                    "target": {"entity_id": "light.bedroom"},
                    "data": {"brightness": 128, "color_temp": 300},
                }
            ]
        }

        # Mock LLM response
        llm_response = json.dumps(
            [
                {
                    "entity_id": "light.bedroom",
                    "desired_state": "on",
                    "desired_attributes": {"brightness": 128, "color_temp": 300},
                    "confidence": 0.95,
                }
            ]
        )
        mock_llm_router.generate.return_value = llm_response

        # Infer states
        states = await inference_service.infer_from_automation(
            automation_id="automation.morning_routine",
            automation_config=automation_config,
            use_cache=False,
        )

        # Verify result
        assert len(states) == 1
        assert states[0].entity_id == "light.bedroom"
        assert states[0].desired_state == "on"
        assert states[0].desired_attributes == {"brightness": 128, "color_temp": 300}
        assert states[0].confidence == 0.95

        # Verify LLM was called with correct parameters
        mock_llm_router.generate.assert_called_once()
        call_kwargs = mock_llm_router.generate.call_args.kwargs
        assert call_kwargs["complexity"] == TaskComplexity.MODERATE
        assert call_kwargs["temperature"] == 0.3
        assert "light.bedroom" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_infer_media_player_turn_on(self, inference_service, mock_llm_router):
        """Test inference for media_player.turn_on action."""
        automation_config = {
            "action": [
                {
                    "service": "media_player.turn_on",
                    "target": {"entity_id": "media_player.living_room"},
                }
            ]
        }

        llm_response = json.dumps(
            [
                {
                    "entity_id": "media_player.living_room",
                    "desired_state": "on",
                    "confidence": 0.9,
                }
            ]
        )
        mock_llm_router.generate.return_value = llm_response

        states = await inference_service.infer_from_automation(
            automation_id="automation.media_control",
            automation_config=automation_config,
            use_cache=False,
        )

        assert len(states) == 1
        assert states[0].entity_id == "media_player.living_room"
        assert states[0].desired_state == "on"
        assert states[0].desired_attributes is None
        assert states[0].confidence == 0.9

    @pytest.mark.asyncio
    async def test_infer_climate_set_temperature(self, inference_service, mock_llm_router):
        """Test inference for climate.set_temperature action."""
        automation_config = {
            "action": [
                {
                    "service": "climate.set_temperature",
                    "target": {"entity_id": "climate.thermostat"},
                    "data": {"temperature": 22},
                }
            ]
        }

        llm_response = json.dumps(
            [
                {
                    "entity_id": "climate.thermostat",
                    "desired_state": "heat",
                    "desired_attributes": {"temperature": 22},
                    "confidence": 0.85,
                }
            ]
        )
        mock_llm_router.generate.return_value = llm_response

        states = await inference_service.infer_from_automation(
            automation_id="automation.climate_control",
            automation_config=automation_config,
            use_cache=False,
        )

        assert len(states) == 1
        assert states[0].entity_id == "climate.thermostat"
        assert states[0].desired_state == "heat"
        assert states[0].desired_attributes == {"temperature": 22}
        assert states[0].confidence == 0.85

    @pytest.mark.asyncio
    async def test_infer_switch_turn_off(self, inference_service, mock_llm_router):
        """Test inference for switch.turn_off action."""
        automation_config = {
            "action": [
                {
                    "service": "switch.turn_off",
                    "target": {"entity_id": "switch.outlet"},
                }
            ]
        }

        llm_response = json.dumps(
            [
                {
                    "entity_id": "switch.outlet",
                    "desired_state": "off",
                    "confidence": 0.95,
                }
            ]
        )
        mock_llm_router.generate.return_value = llm_response

        states = await inference_service.infer_from_automation(
            automation_id="automation.turn_off_outlet",
            automation_config=automation_config,
            use_cache=False,
        )

        assert len(states) == 1
        assert states[0].entity_id == "switch.outlet"
        assert states[0].desired_state == "off"
        assert states[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_infer_multiple_actions(self, inference_service, mock_llm_router):
        """Test inference for automation with multiple actions."""
        automation_config = {
            "action": [
                {
                    "service": "light.turn_on",
                    "target": {"entity_id": "light.bedroom"},
                    "data": {"brightness": 255},
                },
                {
                    "service": "switch.turn_off",
                    "target": {"entity_id": "switch.fan"},
                },
            ]
        }

        llm_response = json.dumps(
            [
                {
                    "entity_id": "light.bedroom",
                    "desired_state": "on",
                    "desired_attributes": {"brightness": 255},
                    "confidence": 0.95,
                },
                {
                    "entity_id": "switch.fan",
                    "desired_state": "off",
                    "confidence": 0.9,
                },
            ]
        )
        mock_llm_router.generate.return_value = llm_response

        states = await inference_service.infer_from_automation(
            automation_id="automation.bedtime",
            automation_config=automation_config,
            use_cache=False,
        )

        assert len(states) == 2
        assert states[0].entity_id == "light.bedroom"
        assert states[1].entity_id == "switch.fan"

    @pytest.mark.asyncio
    async def test_confidence_clamping(self, inference_service, mock_llm_router):
        """Test that confidence scores are clamped to valid range."""
        automation_config = {"action": [{"service": "light.turn_on"}]}

        # LLM returns invalid confidence scores
        llm_response = json.dumps(
            [
                {
                    "entity_id": "light.test",
                    "desired_state": "on",
                    "confidence": 1.5,  # Too high
                },
            ]
        )
        mock_llm_router.generate.return_value = llm_response

        states = await inference_service.infer_from_automation(
            automation_id="automation.test",
            automation_config=automation_config,
            use_cache=False,
        )

        # Confidence should be clamped to 1.0
        assert states[0].confidence == 1.0

    @pytest.mark.asyncio
    async def test_parse_llm_response_with_markdown(self, inference_service):
        """Test parsing LLM response wrapped in markdown code blocks."""
        response = """Here is the analysis:

```json
[
  {
    "entity_id": "light.test",
    "desired_state": "on",
    "confidence": 0.8
  }
]
```"""

        states = inference_service._parse_llm_response(response)

        assert len(states) == 1
        assert states[0].entity_id == "light.test"
        assert states[0].desired_state == "on"
        assert states[0].confidence == 0.8

    @pytest.mark.asyncio
    async def test_parse_llm_response_invalid_json(self, inference_service):
        """Test handling of invalid JSON response."""
        response = "This is not valid JSON"

        states = inference_service._parse_llm_response(response)

        assert states == []

    @pytest.mark.asyncio
    async def test_parse_llm_response_missing_fields(self, inference_service):
        """Test handling of response with missing required fields."""
        response = json.dumps(
            [
                {"entity_id": "light.test"},  # Missing desired_state
                {"desired_state": "on"},  # Missing entity_id
            ]
        )

        states = inference_service._parse_llm_response(response)

        # Both items should be skipped
        assert states == []

    @pytest.mark.asyncio
    async def test_infer_invalid_config_no_action(self, inference_service):
        """Test error handling for config without action key."""
        automation_config = {"trigger": [{"platform": "time"}]}

        with pytest.raises(ValueError, match="must contain 'action' key"):
            await inference_service.infer_from_automation(
                automation_id="automation.test",
                automation_config=automation_config,
                use_cache=False,
            )

    @pytest.mark.asyncio
    async def test_infer_empty_actions(self, inference_service):
        """Test handling of automation with empty actions list."""
        automation_config = {"action": []}

        states = await inference_service.infer_from_automation(
            automation_id="automation.empty",
            automation_config=automation_config,
            use_cache=False,
        )

        assert states == []

    @pytest.mark.asyncio
    async def test_infer_llm_failure(self, inference_service, mock_llm_router):
        """Test handling when LLM fails to generate response."""
        automation_config = {
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.test"}}]
        }

        # LLM returns None (failure)
        mock_llm_router.generate.return_value = None

        states = await inference_service.infer_from_automation(
            automation_id="automation.test",
            automation_config=automation_config,
            use_cache=False,
        )

        assert states == []

    @pytest.mark.asyncio
    async def test_store_inferred_states(self, inference_service):
        """Test storing inferred states in database."""
        inferred_states = [
            InferredState(
                entity_id="light.bedroom",
                desired_state="on",
                desired_attributes={"brightness": 128},
                confidence=0.95,
            ),
            InferredState(
                entity_id="switch.fan",
                desired_state="off",
                confidence=0.9,
            ),
        ]

        # Mock database session
        mock_session = AsyncMock()
        inference_service.database.async_session.return_value.__aenter__.return_value = mock_session

        await inference_service._store_inferred_states(
            automation_id="automation.test",
            inferred_states=inferred_states,
        )

        # Verify delete was called to clear old states
        assert mock_session.execute.call_count == 1  # delete statement
        assert mock_session.commit.call_count == 1

        # Verify records were added
        assert mock_session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_get_cached_states(self, inference_service):
        """Test retrieving cached states from database."""
        # Mock database records
        mock_record1 = MagicMock(spec=AutomationDesiredState)
        mock_record1.entity_id = "light.bedroom"
        mock_record1.desired_state = "on"
        mock_record1.desired_attributes = {"brightness": 128}
        mock_record1.confidence = 0.95

        mock_record2 = MagicMock(spec=AutomationDesiredState)
        mock_record2.entity_id = "switch.fan"
        mock_record2.desired_state = "off"
        mock_record2.desired_attributes = None
        mock_record2.confidence = 0.9

        # Mock session and query result
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record1, mock_record2]
        mock_session.execute.return_value = mock_result

        inference_service.database.async_session.return_value.__aenter__.return_value = mock_session

        # Get cached states
        states = await inference_service._get_cached_states("automation.test")

        # Verify results
        assert states is not None
        assert len(states) == 2
        assert states[0].entity_id == "light.bedroom"
        assert states[0].desired_state == "on"
        assert states[1].entity_id == "switch.fan"
        assert states[1].desired_state == "off"

    @pytest.mark.asyncio
    async def test_get_cached_states_not_found(self, inference_service):
        """Test retrieving cached states when none exist."""
        # Mock empty query result
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        inference_service.database.async_session.return_value.__aenter__.return_value = mock_session

        states = await inference_service._get_cached_states("automation.test")

        assert states is None

    @pytest.mark.asyncio
    async def test_infer_with_cache_hit(self, inference_service, mock_llm_router):
        """Test that cached states are used when available."""
        automation_config = {"action": [{"service": "light.turn_on"}]}

        # Mock cached states
        cached_states = [
            InferredState(
                entity_id="light.cached",
                desired_state="on",
                confidence=0.95,
            )
        ]

        with patch.object(inference_service, "_get_cached_states", return_value=cached_states):
            states = await inference_service.infer_from_automation(
                automation_id="automation.test",
                automation_config=automation_config,
                use_cache=True,
            )

        # Verify cached states were returned
        assert states == cached_states

        # Verify LLM was NOT called
        mock_llm_router.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_infer_with_cache_disabled(self, inference_service, mock_llm_router):
        """Test that cache is bypassed when use_cache=False."""
        automation_config = {"action": [{"service": "light.turn_on"}]}

        llm_response = json.dumps(
            [{"entity_id": "light.fresh", "desired_state": "on", "confidence": 0.9}]
        )
        mock_llm_router.generate.return_value = llm_response

        with patch.object(inference_service, "_get_cached_states", return_value=[MagicMock()]):
            states = await inference_service.infer_from_automation(
                automation_id="automation.test",
                automation_config=automation_config,
                use_cache=False,
            )

        # Verify LLM was called despite cache
        mock_llm_router.generate.assert_called_once()
        assert states[0].entity_id == "light.fresh"

    @pytest.mark.asyncio
    async def test_build_inference_prompt(self, inference_service):
        """Test prompt building from automation actions."""
        actions = [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.bedroom"},
                "data": {"brightness": 128},
            }
        ]

        prompt = inference_service._build_inference_prompt("automation.test", actions)

        # Verify prompt contains key information
        assert "automation.test" in prompt
        assert "light.turn_on" in prompt
        assert "light.bedroom" in prompt
        assert "brightness" in prompt
        assert "128" in prompt
