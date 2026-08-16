"""Mock Adapter / Mock Device：完全模拟的空调设备（v3.0 §46）。

用于 M1A 模拟闭环，不接触任何真实设备。
MockDevice 模拟一个可被 IR 控制的空调：
- turn_on / turn_off / set_temperature
- 支持"验证证据"注入（模拟 V2/V3/V4）
- 可注入故障（actuation 失败、验证超时等）
"""

from __future__ import annotations

from typing import Any

from physical_agent.adapters.base import (
    Device,
    DeviceState,
    ExecutionEvidence,
)


class MockDevice:
    """模拟空调。"""

    def __init__(self, device_id: str = "mock.ac.bedroom") -> None:
        self.device_id = device_id
        self.power: str = "off"
        self.temperature: int = 26
        self.mode: str = "cool"
        self.current_temp: float = 28.0
        self._fail_actuation: bool = False
        self._evidence_level: str = "V2"

    def set_fault(self, fail_actuation: bool = False, evidence_level: str = "V2") -> None:
        """注入故障：actuation 失败，或限制证据层级。"""
        self._fail_actuation = fail_actuation
        self._evidence_level = evidence_level

    def turn_on(self, temperature: int, mode: str) -> None:
        if self._fail_actuation:
            raise RuntimeError("mock actuation failure")
        self.power = "on"
        self.temperature = temperature
        self.mode = mode
        self.current_temp = float(temperature) - 2.0  # 模拟开始降温

    def turn_off(self) -> None:
        self.power = "off"

    def set_temperature(self, temperature: int) -> None:
        if self.power == "off":
            raise RuntimeError("cannot set temperature while off")
        self.temperature = temperature

    def observe(self) -> dict[str, Any]:
        return {
            "power": self.power,
            "temperature": self.temperature,
            "mode": self.mode,
            "current_temp": self.current_temp,
        }


class MockAdapter:
    """模拟空调的 DeviceAdapter。"""

    def __init__(self, device: MockDevice | None = None) -> None:
        self._device = device or MockDevice()

    async def discover(self) -> list[Device]:
        return [
            Device(
                device_id=self._device.device_id,
                device_type="climate",
                capabilities=[
                    "home.climate.turn_on",
                    "home.climate.turn_off",
                    "home.climate.set_temperature",
                ],
            )
        ]

    async def observe(self, device_id: str) -> DeviceState:
        return DeviceState(device_id=device_id, state=self._device.observe(), available=True)

    async def execute(self, request: Any) -> ExecutionEvidence:
        params = request.parameters
        try:
            if request.capability_id == "home.climate.turn_on":
                self._device.turn_on(params["temperature"], params.get("mode", "cool"))
            elif request.capability_id == "home.climate.turn_off":
                self._device.turn_off()
            elif request.capability_id == "home.climate.set_temperature":
                self._device.set_temperature(params["temperature"])
            else:
                return ExecutionEvidence(
                    correlation_id=request.correlation_id,
                    dispatched=False,
                    physical_effect="failed",
                )
        except RuntimeError as exc:
            return ExecutionEvidence(
                correlation_id=request.correlation_id,
                dispatched=False,
                physical_effect="failed",
                detail={"error": str(exc)},
            )

        return ExecutionEvidence(
            correlation_id=request.correlation_id,
            dispatched=True,
        )

    async def verify(self, execution: ExecutionEvidence) -> ExecutionEvidence:
        """按注入的证据层级返回验证证据。"""
        if not execution.dispatched:
            return execution
        # 依据 mock device 当前状态和注入的证据层级，构造 V2/V3/V4 证据
        level = self._device._evidence_level
        exec_dict = execution.model_dump()
        exec_dict["actuation_observed"] = True  # V2：IR 发射被观测
        if level in ("V3", "V4"):
            exec_dict["device_evidence"] = True  # V3：设备蜂鸣/面板
        if level == "V4":
            exec_dict["physical_effect_verified"] = True  # V4：温度下降
            exec_dict["physical_effect"] = "confirmed"
        elif self._device.power == "on":
            exec_dict["physical_effect"] = "pending"
        return ExecutionEvidence(**exec_dict)
