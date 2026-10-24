"""Local device-reported telemetry sensors."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TrekCoordinator
from .entity import TrekEntity

PARALLEL_UPDATES = 0

SENSORS = (
    *(
        SensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=device_class,
            native_unit_of_measurement=unit,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=precision,
        )
        for key, device_class, unit, precision in (
            ("ac_input_power", SensorDeviceClass.POWER, UnitOfPower.WATT, 0),
            ("battery_power", SensorDeviceClass.POWER, UnitOfPower.WATT, 0),
            ("ac_input_current", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, 1),
            ("battery_current", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, 1),
        )
    ),
    SensorEntityDescription(
        key="charging_status",
        translation_key="charging_status",
        device_class=SensorDeviceClass.ENUM,
        options=["charging", "discharging", "idle"],
        icon="mdi:battery-sync-outline",
    ),
    *(
        SensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=device_class,
            native_unit_of_measurement=unit,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=1,
        )
        for key, device_class, unit in (
            ("ac_input_voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT),
            ("inverter_voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT),
            ("ac_input_frequency", SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ),
            ("inverter_frequency", SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ),
            (
                "battery_cell_temperature_max",
                SensorDeviceClass.TEMPERATURE,
                UnitOfTemperature.CELSIUS,
            ),
            (
                "battery_cell_temperature_min",
                SensorDeviceClass.TEMPERATURE,
                UnitOfTemperature.CELSIUS,
            ),
        )
    ),
    *(
        SensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        )
        for key in ("dc_barrel_output_power", "dc_rv_output_power", "dc_car_output_power")
    ),
    SensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="output_power",
        translation_key="output_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ac_output_power",
        translation_key="ac_output_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="usb_a_output_power",
        translation_key="usb_a_output_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="usb_c_output_power",
        translation_key="usb_c_output_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery_health",
        translation_key="battery_health",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery-heart-variant",
    ),
    *(
        SensorEntityDescription(
            key=f"internal_temperature_{index}",
            translation_key=f"internal_temperature_{index}",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        for index in range(1, 6)
    ),
    *(
        SensorEntityDescription(
            key=key,
            translation_key=key,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:information-outline",
        )
        for key in (
            "serial_number",
            "hardware_version",
            "communications_firmware",
            "dsp_firmware",
            "bms_firmware",
            "reported_software_version",
        )
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[TrekCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        TrekSensor(entry.runtime_data, entry, description) for description in SENSORS
    )


class TrekSensor(TrekEntity, SensorEntity):
    def __init__(
        self, coordinator: TrekCoordinator, entry: ConfigEntry, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | float | str | None:
        return getattr(self.coordinator.data, self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, int | None] | None:
        if self.entity_description.key == "charging_status":
            return {"reported_code": self.coordinator.data.charging_status_code}
        return None
