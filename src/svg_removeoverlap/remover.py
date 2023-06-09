#!/usr/bin/env python3
import logging
from pathlib import Path
import sys
from typing import List, Union

import picosvg.svg
import picosvg.svg_pathops
from lxml import etree
from tqdm import tqdm
import tinycss2

logger = logging.getLogger(__name__)

from lxml import etree

def get_css_fill(style: str) -> str:
    """Extract the fill value from a CSS style string.

    Args:
        style (str): The CSS style string.

    Returns:
        str: The fill value found in the CSS style string.
    """
    try:
        return (
            next(
                (
                    token.value[0].serialize()
                    for token in tinycss2.parse_declaration_list(style)
                    if hasattr(token, "name") and token.name == "fill"
                ),
                "",
            )
            .replace(" ", "")
            .lower()
        )
    except ValueError:
        return ""

class RemoveOverlapsSVG:
    def __init__(
        self,
        cairo: bool = True,
        picofy: bool = False,
        keep_white: bool = False,
        skip_svg_fills: List[str] = None,
        verbose: bool = False,
    ) -> None:
        """Initialize RemoveOverlapsSVG class.

        Args:
            cairo (bool, optional): Use CairoSVG for SVG conversion. Defaults to True.
            picofy (bool, optional): Convert SVG to picosvg. Defaults to False.
            keep_white (bool, optional): Keep white fill shapes. Defaults to False.
            skip_svg_fills (List[str], optional): List of fill values to skip. Defaults to a list of common white and transparent fill values.
            verbose (bool, optional): Enable verbose logging. Defaults to False.
        """
        self.skip_svg_fills: List[str] = skip_svg_fills or [
            "white",
            "rgb(255,255,255)",
            "rgb(100%,100%,100%)",
            "rgba(255,255,255,1)",
            "hsl(0,0%,100%)",
            "hsla(0,0%,100%,1)",
            "transparent",
            "#ffffff",
            "none",
        ]
        self.cairo: bool = cairo
        self.picofy: bool = picofy
        self.keep_white: bool = keep_white
        self.verbose: bool = verbose
        if verbose:
            logging.basicConfig(level=logging.INFO)
        self.svg_content: str = None
        self.pico: picosvg.svg.SVG = None

    def _protect_clipPaths(self, svg_bytes: bytes) -> str:
        """Protect clipPaths by setting their fill to transparent.

        Args:
            svg_bytes (bytes): SVG content as bytes.

        Returns:
            str: Modified SVG content as string.
        """
        try:
            root = etree.fromstring(svg_bytes)
        except (etree.XMLSyntaxError, etree.LxmlError) as err:
            raise ValueError(f"Invalid SVG content: {err}") from err
        clip_paths = root.findall(".//{http://www.w3.org/2000/svg}clipPath")
        for clip_path in clip_paths:
            paths = clip_path.findall("{http://www.w3.org/2000/svg}path")
            for path in paths:
                path.set("fill", "transparent")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True).decode(
            "utf-8"
        )

    def _prep_svg_cairo(self) -> None:
        """Prepare the SVG content for CairoSVG conversion."""
        from cairosvg.surface import SVGSurface

        try:
            self.svg_content = self._protect_clipPaths(
                SVGSurface.convert(bytestring=bytes(self.svg_content, encoding="utf-8"))
            )
        except Exception as e:
            print(f"Error: {e}")
            print("Error: SVG content:")
            print(self.svg_content)
        else:
            print("CairoSVG conversion successful")

    def save_svg(self, output_path: Union[str, Path]) -> None:
        """Save the SVG content to a file.

        Args:
            output_path (Union[str, Path]): The path of the output file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Saving {output_path}...")
        with open(output_path, "w") as output_file:
            output_file.write(self.svg_content)

    def load_svg(self, input_path: Union[str, Path]) -> None:
        """Load an SVG file and read its content.

        Args:
            input_path (Union[str, Path]): The path of the input file.
        """
        if not input_path:
            raise ValueError("The input path cannot be empty.")

        input_path = Path(input_path)

        if not input_path.exists():
            raise FileNotFoundError(f"The input path {input_path} does not exist.")

        if not input_path.is_file():
            raise NotADirectoryError(f"The input path {input_path} is not a file.")

        logger.info(f"Reading {input_path}...")
        with open(input_path, "r") as svg_file:
            self.svg_content = svg_file.read()
        if self.cairo:
            self._prep_svg_cairo()

    def _parse_svg(self):
        """Parse the SVG content and create an SVG object using picosvg."""
        logger.info("Parsing SVG...")
        try:
            self.pico = picosvg.svg.SVG.fromstring(self.svg_content)
        except (picosvg.svg.SVGParseError, ValueError) as e:
            logger.error(f"Failed to parse SVG: {e}")
            raise

    def _picofy_svg(self):
        """Convert the SVG object to a picosvg representation if the 'picofy' option is enabled."""
        if self.picofy:
            logger.info("Picofying SVG...")
            try:
                self.pico = self.pico.topicosvg()
                self.svg_content = self.pico.tostring(pretty_print=False)
            except Exception as e:
                logger.warn("Failed to picofy SVG: %s", e)

    def _prep_pico(self):
        """Prepare the picosvg object by parsing the SVG content and optionally converting it to a picosvg representation."""
        try:
            self._parse_svg()
            self._picofy_svg()
        except Exception as e:
            self._picosvg = None
            self._picosvg_error = e

    def _filter_pico_shapes(self):
        """Filter the shapes in the picosvg object based on their fill values.

        Returns:
            List[picosvg.svg.Shapes]: A list of filtered shapes.
        """
        shapes = []
        for shape in tqdm(
            self.pico.shapes(),
            desc="Converting paths",
            disable=not self.verbose or not sys.stdout.isatty(),
        ):
            fill = get_css_fill(shape.style) or shape.fill.replace(" ", "").lower()
            if (self.keep_white) or (fill not in self.skip_svg_fills):
                shapes.append(shape)
        return shapes


    def remove_overlaps_pico(self, sequential: bool = False) -> None:
        """Remove overlaps in the SVG using picosvg.

        Args:
            sequential (bool, optional): Remove overlaps sequentially. Defaults to False.
        """
        self._prep_pico()
        shapes = self._filter_pico_shapes()
        clip_rule = "nonzero"
        clip_rules = [clip_rule] * len(shapes)

        if sequential:
            new_shape = shapes[0]
            for shape in tqdm(
                shapes[1:],
                desc="Removing overlaps",
                disable=not self.verbose or not sys.stdout.isatty(),
            ):
                new_shape = picosvg.svg_pathops.union(
                    [new_shape, shape], [clip_rule, clip_rule]
                )
        else:
            logger.info("Removing overlaps...")
            new_shape = picosvg.svg_pathops.union(shapes, clip_rules)
        union_d = picosvg.svg.SVGPath.from_commands(new_shape).d
        new_root = etree.Element("svg")
        for a, v in self.pico.svg_root.attrib.items():
            new_root.set(a, v)
        new_root.set("xmlns", "http://www.w3.org/2000/svg")
        new_svg = picosvg.svg.SVG(new_root)
        new_svg.view_box = self.pico.view_box
        path_el = etree.SubElement(new_root, "path")
        path_el.set("d", union_d)
        self.pico = new_svg
        self.svg_content = self.pico.tostring(pretty_print=True)

    def remove(self, sequential: bool = False) -> None:
        """Remove overlaps in the SVG.

        Args:
            sequential (bool, optional): Remove overlaps sequentially. Defaults to False.
        """
        self.remove_overlaps_pico(sequential=sequential)

