from openglider.lines.line_types.linetype import LineType
from openglider.utils.colors import Color


def A8001(strength: int, diameter: float, weight: float) -> None:
    LineType(
        f"edelrid.A-8001-{strength:03d}",
        diameter,
        [[10*strength, 5.]],
        10*strength,
        weight,
        sheated=False,
        colors={
            "orange": Color.parse_hex("ff6600"),
            "blue": Color.parse_hex("0f52ba"),
            "magenta": Color.parse_hex("c92351"),
            "nature": Color.parse_hex("CABB84")
        }
    )

edelrid_colors: dict[str, Color | None] = {
    "sky": Color.parse_hex("0095D8"),
    "yellow": Color.parse_hex("FFDD00"),
    "green": Color.parse_hex("009037"),
    "fluored": Color.parse_hex("EB6A27"),
    "red": Color.parse_hex("E2001A"),
}

def A6843(strength: int, diameter: float, weight: float) -> None:
    LineType(
        f"edelrid.A-6843-{strength:03d}",
        diameter,
        [[10*strength, 5.]],
        10*strength,
        weight,
        sheated=True,
        colors=edelrid_colors.copy()
    )


A8001(25, 0.4, 0.15)
A8001(50, 0.5, 0.25)
A8001(70, 0.7, 0.4)
A8001(90, 0.8, 0.55)
A8001(130, 1.0, 0.8)
A8001(135, 1.1, 0.85)
A8001(190, 1.2, 1.1)
A8001(230, 1.5, 1.4)
A8001(280, 1.7, 1.7)
A8001(340, 1.9, 2.1)
A8001(470, 2.2, 2.8)

A6843(140, 1.4, 1.5)
A6843(180, 1.5, 1.8)
A6843(230, 1.9, 2.8)
A6843(280, 2.1, 3.2)
A6843(370, 2.4, 4.6)

LineType("edelrid.7850-240", 1.58, 2.8, 2120, 1, True, colors=edelrid_colors.copy())

def A7343(strength: int, diameter: float, weight: float) -> None:
    LineType(
        f"edelrid.A-7343-{strength:03d}",
        diameter,
        [[10*strength, 5.]],
        10*strength,
        weight,
        sheated=True,
        colors={
            "fluored": Color.parse_hex("f70000"),
            "sky": Color.parse_hex("b2d4dd"),
            "citrus": Color.parse_hex("f5ff00"),
            "turquoise": Color.parse_hex("44bbca")
        }
    )

A7343(75, 1.0, 0.70)
A7343(90, 1.2, 1.10)
A7343(140, 1.3, 1.40)
A7343(190, 1.5, 1.80)
A7343(230, 1.7, 2.40)
A7343(280, 1.8, 2.60)
A7343(340, 2.1, 3.70)
A7343(420, 2.3, 4.10)
A7343(500, 2.3, 4.10)