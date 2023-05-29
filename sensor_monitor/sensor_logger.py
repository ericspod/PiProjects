import time
import datetime
import traceback
from pathlib import Path
from csv import DictWriter
from enum import Enum
from itertools import cycle
from collections import OrderedDict, defaultdict
from colorsys import rgb_to_hls, hls_to_rgb
from io import BytesIO

import numpy as np
import click
from PIL import Image, ImageDraw, ImageFont
import mics6814
import bme680
import ST7789
import bh1745
import psutil  # only needed for CPU temperature compensation

# set to whatever other font available, installed with "apt install fonts-freefont-ttf"
FONT_FILE = "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf"

cpu_temps = []


def set_lightness(r, g, b, l):
    """Replace the lightness value of the color (`r`, `g`, `b`) by `l`. RGB values 0-255, `l` 0-1."""
    h, _, s = rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    nr, ng, nb = hls_to_rgb(h, l, s)

    return int(nr * 255), int(ng * 255), int(nb * 255)


class Units(Enum):
    """Known units and their symbols."""

    temp = "C"
    ohms = "\u03a9"
    pressure = "hPa"
    humidity = "%RH"
    lux = "lx"
    none = ""


class LEDColors(Enum):
    """Colors to cycle through on the MICS6814."""

    c1 = (20, 0, 0)
    c2 = (0, 20, 0)
    c3 = (0, 0, 20)
    c4 = (0, 20, 20)
    c5 = (20, 0, 20)
    c6 = (20, 20, 0)
    c7 = (20, 20, 20)


class GraphColors(Enum):
    """Colors to use for graphs, if there are more graphs than colors cycle through the list."""

    c1 = set_lightness(0, 63, 92, 0.5)
    c2 = set_lightness(68, 78, 134, 0.5)
    c3 = set_lightness(149, 81, 150, 0.5)
    c4 = set_lightness(221, 81, 130, 0.5)
    c5 = set_lightness(255, 110, 84, 0.5)
    c6 = set_lightness(255, 166, 0, 0.5)
    c7 = set_lightness(166, 255, 0, 0.5)
    c8 = set_lightness(255, 255, 255, 0.7)


def lighten_darken_color(rgb, factor=0.5):
    """
    Light or darken color `rgb` which is a triple of values 0-255. If `factor` is between 0 and 1,
    the color is lighten (0 unchanged, 1 is white). If `factor` is between -1 and 0, the color is
    darkened (0 unchanged, -1 black).
    """
    factor = np.clip(factor, -1.0, 1.0)
    r, g, b = rgb
    h, l, s = rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

    if factor <= 0:
        l = (1 + factor) * l
    else:
        l = 1 - factor * (1 - l)

    nr, ng, nb = hls_to_rgb(h, l, s)

    return int(nr * 255), int(ng * 255), int(nb * 255)


def rgbc_to_rgb(r, g, b, c):
    if c > 0:
        r, g, b = [min(255, int((x / float(c)) * 255)) for x in (r, g, b)]
        return (r, g, b)

    return (0, 0, 0)


def format_value(value, unit):
    """Format the given float value into a string with the given unit, large value ohms reduced to kohms."""
    unit_str = unit.value

    if unit in (Units.ohms, Units.lux) and value > 1000:
        unit_str = "k" + unit_str
        value /= 1000.0

    return f"{value:.3f}{unit_str}"


def compensate_temperature(raw_temp, factor=4.0, smooth_size=10):
    """Adjust the raw temperature value based on the CPU temperature to approximate a true temperature."""
    temps = psutil.sensors_temperatures()
    cpu_temp = temps["cpu_thermal"][0].current
    cpu_temps.append(cpu_temp)

    if len(cpu_temps) > smooth_size:
        cpu_temps[:] = cpu_temps[1:]

    return raw_temp - ((np.average(cpu_temps) - raw_temp) / factor)


def get_gas_baseline(sensor, burn_in_time=300):
    start_time = curr_time = time.time()
    burn_in_data = []

    while curr_time - start_time < burn_in_time:
        curr_time = time.time()
        if sensor.get_sensor_data() and sensor.data.heat_stable:
            gas = sensor.data.gas_resistance
            burn_in_data.append(gas)
            time.sleep(1)

    return sum(burn_in_data[-50:]) / 50.0


def computer_indoor_air_quality(gas, hum, gas_baseline, hum_baseline=40.0, hum_weighting=0.25):
    # from https://github.com/pimoroni/bme680-python/blob/master/examples/indoor-air-quality.py
    gas_offset = gas_baseline - gas
    hum_offset = hum - hum_baseline

    # Calculate hum_score as the distance from the hum_baseline.
    if hum_offset > 0:
        hum_score = 100 - hum_baseline - hum_offset
        hum_score /= 100 - hum_baseline
        hum_score *= hum_weighting * 100
    else:
        hum_score = hum_baseline + hum_offset
        hum_score /= hum_baseline
        hum_score *= hum_weighting * 100

    # Calculate gas_score as the distance from the gas_baseline.
    if gas_offset > 0:
        gas_score = gas / gas_baseline
        gas_score *= 100 - (hum_weighting * 100)
    else:
        gas_score = 100 - (hum_weighting * 100)

    # Calculate air_quality_score.
    return hum_score + gas_score


def collect_data(gas_sensor, env_sensor, light_sensor, gas_baseline, timeout=5, sleep_time=0.01):
    """Collect values from sensors and return as a dictionary."""
    env_ready = env_sensor.get_sensor_data()

    while timeout > 0 and (not env_ready or not env_sensor.data.heat_stable):
        time.sleep(sleep_time)
        env_ready = env_sensor.get_sensor_data()
        timeout -= 1

    if timeout == 0:
        if not env_ready:
            raise IOError("Cannot acquire BME688 data")
        elif not env_sensor.data.heat_stable:
            raise IOError("BME680 heat not stable")

    r, g, b, c = light_sensor.get_rgbc_raw()

    iaq = computer_indoor_air_quality(env_sensor.data.gas_resistance, env_sensor.data.humidity, gas_baseline)

    return OrderedDict(
        time=str(datetime.datetime.now()),
        temperature=env_sensor.data.temperature,
        pressure=env_sensor.data.pressure,
        humidity=env_sensor.data.humidity,
        gas_resistance=env_sensor.data.gas_resistance,
        iaq=iaq,
        oxidising=gas_sensor.read_oxidising(),
        reducing=gas_sensor.read_reducing(),
        nh3=gas_sensor.read_nh3(),
        r=r,
        g=g,
        b=b,
        c=c,
    )


def log_data_csv(filename, values):
    """Append data lines to a csv file."""
    path = Path(filename)
    exists = path.exists()

    with open(str(path), "a") as o:
        w = DictWriter(o, tuple(values))
        if not exists:
            w.writeheader()

        w.writerow(values)


def draw_sensors(
    sensors,
    bg_color=(20, 20, 20),
    graph_dims=(140, 25),
    spacing=4,
    image_dims=(240, 240),
    light_dark_factor=-0.9,
    dpi=96,
    font_size=12,
    text_color=(200, 200, 200),
):
    """Draw the log graphs and sensor values into a PIL image."""
    startx, starty = spacing - 1, spacing - 1
    graphw, graphh = graph_dims
    colors = cycle(GraphColors)

    font = ImageFont.truetype(FONT_FILE, size=font_size)

    pilim = Image.new("RGB", image_dims, bg_color)
    draw = ImageDraw.Draw(pilim)

    for name, unit, values in sensors:
        col = next(colors).value
        bgcol = lighten_darken_color(col, light_dark_factor)
        last_val = 0

        graph_vals = np.full(graphw, np.nan, np.float32)

        num_vals = min(graphw, len(values))
        if num_vals > 0:
            sel_values = np.asarray(values[-num_vals:])
            graph_vals[-num_vals:] = sel_values
            minv = min(values)
            maxv = max(values)
            diff = (maxv - minv) or 1.0
        else:
            minv = maxv = 0.0
            diff = 1.0

        text_pos = (startx + graphw + spacing, starty)
        text = f"{name}\n{format_value(graph_vals[-1],unit)}"

        draw.rectangle([(startx, starty), (startx + graphw, starty + graphh)], fill=bgcol)
        draw.multiline_text(text_pos, text, font=font, fill=text_color)

        # draw the graph by drawing a vertical line for every value in graph_vals
        for x in range(graphw):
            if np.isnan(graph_vals[x]):
                continue

            y = (graph_vals[x] - minv) / diff
            indy = starty + int((1 - y) * (graphh - 1))
            indx = startx + x

            if 0 <= indy < image_dims[0] and 0 <= indx < image_dims[1]:
                draw.line([(indx, indy), (indx, starty + graphh)], fill=col)

        starty += graphh + spacing

    return pilim


@click.command("sensor_logger")
@click.option(
    "-d",
    "--delay",
    type=float,
    default=1.0,
    show_default=True,
    help="Delay between samples",
)
@click.option(
    "-i",
    "--interval",
    type=int,
    default=60,
    show_default=True,
    help="Display update interval",
)
@click.option(
    "-m",
    "--max_data_len",
    type=int,
    default=60 * 12,
    show_default=True,
    help="Number of samples to store and compute ranges from",
)
@click.option(
    "-l",
    "--logfile",
    type=click.Path(writable=True, resolve_path=True),
    default=datetime.datetime.now().strftime("./sensors_%y%m%d_%H%M%S.csv"),
    show_default=True,
    help="File to log data to",
)
def log_sensor_data(delay, interval, max_data_len, logfile):
    """
    Logs sensor data from the BME688, MICS6814, and BH1745 sensors, displaying graph results on the ST7789 display.
    Readings are taken at DELAY intervals (in seconds), which are logged in CSV form to LOGFILE.
    The program will loop forever until interrupted on the console.
    """
    try:
        env_sensor = bme680.BME680(bme680.I2C_ADDR_PRIMARY)
    except (RuntimeError, IOError):
        env_sensor = bme680.BME680(bme680.I2C_ADDR_SECONDARY)

    env_sensor.set_humidity_oversample(bme680.OS_2X)
    env_sensor.set_pressure_oversample(bme680.OS_4X)
    env_sensor.set_temperature_oversample(bme680.OS_8X)
    env_sensor.set_filter(bme680.FILTER_SIZE_3)
    env_sensor.set_gas_status(bme680.ENABLE_GAS_MEAS)
    env_sensor.set_gas_heater_temperature(320)
    env_sensor.set_gas_heater_duration(150)
    env_sensor.select_gas_heater_profile(0)

    gas_sensor = mics6814.MICS6814()

    light_sensor = bh1745.BH1745()
    light_sensor.setup()
    light_sensor.set_leds(0)
    light_sensor._enable_channel_compensation = False
    # might be sensible values instead of disabling compensation:
    # light_sensor._channel_compensation = (0.9, 0.5, 0.95, 10.0)

    disp = ST7789.ST7789(
        port=0,
        cs=ST7789.BG_SPI_CS_FRONT,  # BG_SPI_CS_BACK or BG_SPI_CS_FRONT
        dc=9,
        backlight=19,  # 18 for back BG slot, 19 for front BG slot.
        spi_speed_hz=80 * 1000 * 1000,
        offset_left=0,
    )
    disp.begin()

    sensor_arrays = defaultdict(list)
    except_retries = 3  # how many times to try recording data if an exception happens
    count = 0
    led_color = cycle(LEDColors)

    draw_values = (
        ("Temperature", Units.temp, sensor_arrays["temperature"]),
        ("Pressure", Units.pressure, sensor_arrays["pressure"]),
        ("Humidity", Units.humidity, sensor_arrays["humidity"]),
        #("Gas Resist", Units.ohms, sensor_arrays["gas_resistance"]),
        ("IAQ", Units.none, sensor_arrays["iaq"]),
        ("Oxidising", Units.ohms, sensor_arrays["oxidising"]),
        ("Reducing", Units.ohms, sensor_arrays["reducing"]),
        ("NH3", Units.ohms, sensor_arrays["nh3"]),
        ("Lightness", Units.lux, sensor_arrays["c"]),
    )

    gas_baseline = get_gas_baseline(env_sensor)

    while except_retries >= 0:
        try:
            start = time.time()
            dat = collect_data(gas_sensor, env_sensor, light_sensor, gas_baseline)

            # adjust for heating from CPU, omit if BME680 is thermally isolated
            dat["temperature"] = compensate_temperature(dat["temperature"])

            log_data_csv(logfile, dat)

            if (count % interval) == 0:
                count = 0
                for k, v in dat.items():
                    sensor_arrays[k][:] = sensor_arrays[k][-max_data_len:] + [v]

                im = draw_sensors(draw_values)
                im.save("sensor_logger.png")
                disp.display(im)

                gas_sensor.set_led(*next(led_color).value)

            count += 1
            tdelta = time.time() - start
            time.sleep(max(0, delay - tdelta))
        except KeyboardInterrupt:
            except_retries = -1
        except Exception as e:
            traceback.print_exc()
            except_retries -= 1
        else:
            except_retries = 3


if __name__ == "__main__":
    log_sensor_data()
