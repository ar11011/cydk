# cydk
Open source, Full-stack standalone handheld Linux computing device built on Raspberry Pi Zero 2W., embedding real-time hardware with custom firmware and architecture delivered as a self-sustained product

![](https://github.com/ar11011/cydk/blob/main/images/proto%20concept%20rear.png?raw=true)

## Hardware
- **SBC**: Raspberry Pi Zero 2W
- **Display**: Waveshare 3.5" SPI LCD (G), ST7796S driver, 480×320
- **Input**: Adafruit mini Gamepad & HW-040 rotary encoder
- **Power**: 3000mAh + SeeedStudio LiPo Rider Plus
- **Haptic feedback**: passive buzzer & vibration motor

## Software
- Custom PIL-based rendering pipeline
- Modular screen-stack GUI architecture (`core/`, `templates/`, `submenu/`)
- Unified input abstraction layer merging encoder and gamepad inputs into a single event stream
- systemd-managed autostart with a hardware watchdog/kill-switch button and automatic crash recovery

## Status
Actively in development — core GUI, navigation, and hardware I/O are working 
end-to-end. Games/music submenus, settings, and power management are in progress.
