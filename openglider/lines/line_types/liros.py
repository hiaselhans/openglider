from openglider.lines.line_types.linetype import LineType
from openglider.utils.colors import Color


LineType("liros.ltc25", 0.39, [[250, 4.8]], 250, 0.13, False)

LineType("liros.ltc45", 0.55, [[100, 0.85]], 450, 0.28, False)

LineType("liros.ltc65", 0.65, [[100, 0.8]], 650, 0.45, False)

LineType("liros.ltc80", 0.7, [[100, 0.65],
                               [300, 1.65]], 800, 0.57, False)

LineType("liros.ltc120", 1.1, [[100, 0.6],
                               [300, 1.2]], 1200, 0.84, False)

LineType("liros.ltc160", 1.2, [[100, 0.55],
                               [300, 1.05]], 1600, 1.17, False)

LineType("liros.ltc200", 1.3, [[100, 0.6],
                               [300, 1.1]], 2000, 1.42, False)

LineType("liros.ltc350", 1.75, [[100, 0.35],
                                [300, 0.8]], 3500, 2.16, False)

LineType("liros.ltc400", 1.9, [[100, 0.35],
                               [300, 0.89]], 4000, 2.89, False)


LineType("liros.ntsl120", 1.25, [[100, 0.29],
                                 [300, 0.94]], 1200, 1.24, True)

LineType("liros.ntsl160", 1.4, [[100, 0.235],
                                [300, 0.797]], 1600, 1.52, True)

LineType("liros.ntsl200", 1.9, [[100, 0.55],
                                [300, 1.34]], 2000, 2.66, True)

LineType("liros.ntsl250", 2.15, [[100, 0.46],
                                 [300, 1.38]], 2500, 3.37, True)

LineType("liros.ntsl350", 2.25, [[100, 0.23],
                                 [300, 0.46]], 3500, 3.46, True)


def tsl(name: int | str, diameter: float, tension: list[list[float]], strength: float, weight: float) -> None:
    LineType(
        f"liros.tsl{name}",
        diameter,
        tension,
        strength,
        weight,
        sheated=True,
        colors={
            "blue": Color.parse_hex("0095D8"),
            "yellow": Color.parse_hex("FFDD00"),
            "green": Color.parse_hex("009037"),
            "orange": Color.parse_hex("EB6A27"),
            "red": Color.parse_hex("E2001A"),
        }
    )

tsl("090", 1.2, [[100, 0.45], [300, 1.38]], 900, 1.06)

tsl(115, 1.25, [[100, 0.42], [300, 1.21]], 1150, 1.18)

tsl(140, 1.3, [[100, 0.25], [300, 0.88]], 1400, 1.39)

tsl(190, 1.55, [[100, 0.25], [300, 0.71]], 1900, 1.76)

tsl(220, 1.65, [[100, 0.29], [300, 0.75]], 2200, 2.12)

tsl(280, 1.8, [[100, 0.17], [300, 0.46]], 2800, 2.55)

tsl(380, 2.2, [[100, 0.18], [300, 0.46]], 3800, 3.46)

tsl(500, 2.37, [[100, 0.16], [300, 0.42]], 5000, 4.6)

# DFL: Brake line
def dfl(name: str, diameter: float, elongation: float, strength: float, weight: float) -> None:
    LineType(
        f"liros.dfl{name}",
        diameter,
        elongation,
        strength,
        weight,
        colors={
            "yellow": Color.parse_hex("FFDD00"),
            "orange": Color.parse_hex("EB6A27"),
            "red": Color.parse_hex("E2001A"),
        }
    )

dfl("115", 1.4, 3.3, 1150, 1.18)

dfl("s200", 2., 3.6, 2000, 3.1)

dfl("p232", 1.9, 3.4, 2000, 2.58)

dfl("350", 2.7, 3.5, 3500, 4.98)


LineType("liros.dsl25", 0.8, [[340, 3.7]], 250, 0.53, True)

LineType("liros.dsl35", 0.9, [[380, 3.6]], 350, 0.64, True)

LineType("liros.dsl70", 0.95, [[100, 0.19], [300, 0.41]], 700, 0.67, True)

LineType("liros.dsl110", 1.2, [[100, 0.23], [300, 0.73]], 1100, 1.02, True)

LineType("liros.dsl140", 1.25, [[100, 0.54], [300, 0.42]], 1400, 1.14, True)

LineType("liros.dsl350", 2., [[100, 0.15], [300, 0.33]], 3500, 3.25, True)

LineType("liros.dsl600", 2.4, [[100, 0.08], [300, 0.24]], 6000, 4.3, True)

def lirosdc(name: int, thickness: float, elongation: float, break_load: float, weight: float) -> None:
    LineType(
        f"liros.dc{name}",
        thickness,
        elongation,
        break_load,
        weight,
        False,
        colors={
            "white": Color.parse_hex("FFFFFF"),
            "silver": Color.parse_hex("A3A3AC"),
            "black": Color.parse_hex("000000"),
            "green": Color.parse_hex("009037"),
            "red": Color.parse_hex("E2001A"),
            "yellow": Color.parse_hex("FFDD00"),
            "blue": Color.parse_hex("006AB3")
        }
    )

lirosdc(35, 0.38, 2.5, 350, 0.11)
lirosdc(40, 0.5, 2.2, 400, 0.19)
lirosdc(60, 0.6, 3.2, 600, 0.24)
lirosdc(100, 0.8, 3., 1000, 0.42)
lirosdc(120, 0.85, 1.9, 1200, 0.59)
lirosdc(160, 1.1, 2.3, 1600, 0.87)
lirosdc(200, 1.6, 3.7, 2000, 1.42)
lirosdc(300, 1.8, 3.7, 3000, 2.01)
lirosdc(500, 2.5, 3.2, 5000, 2.73)

def ppsl(name: int, thickness: float, stretch: float, max_load: float, weight: float) -> None:
    LineType(
        f"liros.ppsl{name}",
        thickness,
        stretch,
        max_load,
        weight,
        colors={
            "blue": Color.parse_hex("0095D8"),
            "yellow": Color.parse_hex("FFDD00"),
            "green": Color.parse_hex("009037"),
            "orange": Color.parse_hex("EB6A27"),
            "red": Color.parse_hex("E2001A"),
        }
    )

ppsl(120, 1.15, 2.0, 1200, 1)
ppsl(160, 1.4, 3.7, 1600, 1.34)
ppsl(200, 1.42, 2.5, 2000, 1.6)
ppsl(275, 1.9, 2.3, 2750, 2.26)
ppsl(350, 2.25, 2.7, 3500, 3.49)

def ppsls(name: int, thickness: float, stretch: float, max_load: float, weight: float) -> None:
    LineType(
        f"liros.ppsls{name}",
        thickness,
        stretch,
        max_load,
        weight,
        colors={
            "blue": Color.parse_hex("0095D8"),
            "yellow": Color.parse_hex("FFDD00"),
            "green": Color.parse_hex("009037"),
            "orange": Color.parse_hex("EB6A27"),
            "red": Color.parse_hex("E2001A"),
        }
    )

ppsls(65, 0.76, 3.0, 650, 0.4)
ppsls(125, 1.05, 2.7, 1250, 0.89)
ppsls(180, 1.2, 3.2, 1800, 0.92)
ppsls(200, 1.3, 3.0, 2000, 1.65)
ppsls(260, 1.58, 2.8, 2600, 1.98)
