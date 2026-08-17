"""HomeAssistantAdapter：把 Capability Schema 映射到真实 Home Assistant（M1B）。

架构边界（ADR-0001）：
- 本 adapter 是「智能家居/IoT 状态与控制」的 primary adapter，映射命名空间 ``home.*``。
- 它**只做** capability → HA domain/service 的翻译与实体读写，返回结构化
  ``ExecutionEvidence``。**不做** policy / 审批 / 审计（这些由 Capability Gateway 统一执行）。
- 本 adapter **不持有也不落盘**任何 secret；token 仅存在于传入的 ``HomeAssistantClient``。

安全约束（本节内硬性）：
- 实体 domain 必须与 capability domain 一致（例如 ``home.light.turn_on`` 只能作用于
  ``light.*`` 实体），否则 fail-closed 拒绝，防止跨域控制（用灯的 capability 去开 cover）。
- 只暴露白名单 capability；lock/cover/climate/alarm/water_heater/valve 等高风险 domain
  **不会**在本 adapter 内被自动映射为可写动作。
"""

from __future__ import annotations

from physical_agent.adapters.base import Device, DeviceState, ExecutionEvidence
from physical_agent.adapters.ha_client import HomeAssistantClient, HomeAssistantError
from physical_agent.capability.request import CapabilityRequest

# capability 后缀 service → 期望的实体 state（仅用于 read-back 校验，不驱动 action）
_EXPECTED_STATE_BY_SERVICE: dict[str, str] = {
    "turn_on": "on",
    "turn_off": "off",
}

# 每个 entity domain 可暴露的可写 capability 白名单（M1B 只开放低风险 on/off）
_DOMAIN_CAPABILITIES: dict[str, list[str]] = {
    "light": ["home.light.turn_on", "home.light.turn_off"],
    "switch": ["home.switch.turn_on", "home.switch.turn_off"],
}

# 明确禁止作为可写目标的 domain（即使将来误加 capability 也会被拒绝）
_FORBIDDEN_WRITE_DOMAINS = {
    "lock",
    "cover",
    "climate",
    "alarm_control_panel",
    "water_heater",
    "valve",
    "garage_door",
}


class HomeAssistantAdapter:
    """M1B 真实 Home Assistant 设备适配器（实现 DeviceAdapter 协议）。"""

    def __init__(self, client: HomeAssistantClient) -> None:
        self._client = client

    # ---- capability → service 解析 ----

    @staticmethod
    def resolve_service(capability_id: str) -> tuple[str, str]:
        """``home.light.turn_on`` → ``("light", "turn_on")``.

        Raises ``ValueError`` when the capability is not a ``home.<domain>.<service>``
        form or targets a forbidden write domain.
        """
        parts = capability_id.split(".")
        if len(parts) < 3 or parts[0] != "home":
            raise ValueError(f"capability {capability_id!r} is not a home.* capability")

        domain = parts[1]
        service = parts[2]

        if domain in _FORBIDDEN_WRITE_DOMAINS:
            raise ValueError(f"domain {domain!r} is forbidden for direct write via this adapter")

        return domain, service

    # ---- DeviceAdapter 协议 ----

    async def discover(self) -> list[Device]:
        """只读发现：列出 HA 全部实体（不触发任何动作）。"""
        states = await self._client.list_states()
        devices: list[Device] = []
        for entry in states:
            entity_id = entry.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                continue
            domain = entity_id.split(".", 1)[0]
            capabilities = _DOMAIN_CAPABILITIES.get(domain, [])
            devices.append(
                Device(
                    device_id=entity_id,
                    device_type=domain,
                    capabilities=capabilities,
                )
            )
        return devices

    async def observe(self, device_id: str) -> DeviceState:
        """只读观察单个实体的当前状态。"""
        state = await self._client.get_state(device_id)
        return DeviceState(
            device_id=device_id,
            state={
                "state": state.get("state"),
                "attributes": state.get("attributes", {}),
            },
            available=True,
        )

    async def execute(self, request: CapabilityRequest) -> ExecutionEvidence:
        """执行一次 capability → HA service call，返回 ExecutionEvidence。

        不抛异常：一切失败折叠为 ``dispatched=False`` 的 evidence（由 gateway 审计）。
        """
        correlation_id = request.correlation_id

        try:
            domain, service = self.resolve_service(request.capability_id)
        except ValueError as exc:
            return ExecutionEvidence(
                correlation_id=correlation_id,
                dispatched=False,
                physical_effect="failed",
                detail={"error": str(exc)},
            )

        entity_id = request.device_id
        if not entity_id:
            return ExecutionEvidence(
                correlation_id=correlation_id,
                dispatched=False,
                physical_effect="failed",
                detail={"error": "device_id (HA entity_id) is required"},
            )

        # adapter-domain isolation：实体的 domain 必须与 capability domain 一致
        entity_domain = entity_id.split(".", 1)[0]
        if entity_domain != domain:
            return ExecutionEvidence(
                correlation_id=correlation_id,
                dispatched=False,
                physical_effect="failed",
                detail={
                    "error": (
                        f"entity {entity_id!r} domain {entity_domain!r} does not match capability domain {domain!r}"
                    )
                },
            )

        data = {"entity_id": entity_id, **request.parameters}
        try:
            result = await self._client.call_service(domain, service, data)
        except HomeAssistantError as exc:
            return ExecutionEvidence(
                correlation_id=correlation_id,
                dispatched=False,
                physical_effect="failed",
                detail={"error": type(exc).__name__},
            )

        if not result:
            return ExecutionEvidence(
                correlation_id=correlation_id,
                dispatched=False,
                physical_effect="failed",
                detail={"error": "empty service response"},
            )

        return ExecutionEvidence(
            correlation_id=correlation_id,
            dispatched=True,
            detail={
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "expected_state": _EXPECTED_STATE_BY_SERVICE.get(service),
            },
        )

    async def verify(self, execution: ExecutionEvidence) -> ExecutionEvidence:
        """读回实体状态，产出 device evidence（V3）。

        灯/开关无法用独立物理传感器验证（V4），因此 ``physical_effect_verified`` 恒为
        False；read-back 命中只证明「设备上报了目标状态」（V3 device_evidence）。
        """
        if not execution.dispatched:
            return execution

        entity_id = execution.detail.get("entity_id")
        expected = execution.detail.get("expected_state")
        if not entity_id:
            return execution

        try:
            state = await self._client.get_state(entity_id)
        except HomeAssistantError:
            return execution

        exec_dict = execution.model_dump()
        # 服务调用被 HA 接受并返回受影响实体 → V2 执行器输出被观测
        exec_dict["actuation_observed"] = True

        current = state.get("state")
        exec_dict["detail"] = {**execution.detail, "read_back_state": current}

        if expected is not None and current == expected:
            # 设备上报了目标状态 → V3 device evidence（不声称 V4 物理效果）
            exec_dict["device_evidence"] = True

        return ExecutionEvidence(**exec_dict)
