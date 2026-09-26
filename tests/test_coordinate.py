import math
import unittest

from scoring.coordinate import (
    CoordinateSpace,
    clip_bbox,
    coordinate_bbox,
    legacy_1000_to_normalized,
    normalized_to_legacy_1000,
    normalized_to_pixel,
    pdf_to_pixel,
    pixel_to_pdf,
    pixel_to_normalized,
    validate_bbox,
)


class CoordinateContractTests(unittest.TestCase):
    def test_pixel_to_normalized_golden_and_non_square(self):
        self.assertEqual(pixel_to_normalized([500, 250, 1500, 750], 2000, 1000),
                         [0.25, 0.25, 0.75, 0.75])
        self.assertEqual(pixel_to_normalized([248, 350.8, 1240, 1754], 2480, 3508),
                         [0.1, 0.1, 0.5, 0.5])

    def test_resolution_independence(self):
        self.assertEqual(pixel_to_normalized([100, 100, 500, 500], 1000, 1000),
                         pixel_to_normalized([200, 200, 1000, 1000], 2000, 2000))

    def test_legacy_conversion_is_explicit(self):
        self.assertEqual(legacy_1000_to_normalized([250, 250, 750, 750]),
                         [0.25, 0.25, 0.75, 0.75])
        self.assertEqual(normalized_to_legacy_1000([0.25, 0.25, 0.75, 0.75]),
                         [250.0, 250.0, 750.0, 750.0])
        self.assertEqual(coordinate_bbox([250, 250, 750, 750],
                                          CoordinateSpace.NORMALIZED_1000)["coordinate_space"],
                         "normalized_1000")

    def test_same_values_have_different_meaning_only_with_metadata(self):
        self.assertEqual(validate_bbox([0, 0, 1, 1], CoordinateSpace.PIXEL), [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(validate_bbox([0, 0, 1, 1], CoordinateSpace.NORMALIZED), [0.0, 0.0, 1.0, 1.0])
        with self.assertRaises(ValueError):
            validate_bbox([0, 0, 1, 1], "missing")

    def test_invalid_and_zero_area_values_are_rejected(self):
        for box in [[-0.1, 0, 0.2, 0.2], [0, 0, 1.1, 0.2],
                    [0, 0, math.nan, 0.2], [0, 0, math.inf, 0.2],
                    [0, 0, 0, 0.2]]:
            with self.subTest(box=box), self.assertRaises(ValueError):
                validate_bbox(box, CoordinateSpace.NORMALIZED)

    def test_round_trip_and_clipping(self):
        normalized = pixel_to_normalized([3, 5, 97, 195], 100, 200)
        self.assertEqual(normalized_to_pixel(normalized, 100, 200), [3, 5, 97, 195])
        self.assertEqual(clip_bbox([-0.1, 0.2, 0.4, 1.2], [0, 0, 1, 1],
                                   CoordinateSpace.NORMALIZED), [0.0, 0.2, 0.4, 1.0])

    def test_new_serialization_is_canonical(self):
        value = coordinate_bbox([0.125, 0.24, 0.435, 0.325], CoordinateSpace.NORMALIZED,
                                reference="page-image")
        self.assertEqual(value["coordinate_space"], "normalized")
        self.assertTrue(all(0 <= x <= 1 for x in value["bbox"]))
        self.assertEqual(value["reference"], "page-image")

    def test_pdf_pixel_transform_keeps_existing_rotation_contract(self):
        from scoring.coordinate import PageCoordinateSpace
        page = PageCoordinateSpace((0, 0, 200, 100), (10, 20, 190, 90), 90)
        pixel = pdf_to_pixel([30, 30, 80, 60], page, scale=2)
        restored = pixel_to_pdf(pixel.as_dict()["bbox"], page, scale=2)
        self.assertAlmostEqual(restored[0], 30, delta=1)
        self.assertAlmostEqual(restored[1], 30, delta=1)
        self.assertAlmostEqual(restored[2], 80, delta=1)
        self.assertAlmostEqual(restored[3], 60, delta=1)


if __name__ == "__main__":
    unittest.main()
