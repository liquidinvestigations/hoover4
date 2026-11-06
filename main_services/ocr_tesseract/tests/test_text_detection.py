"""Verify the text detection chain and its route on images with known content."""

import base64
import io

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont

import ocr_tesseract as service
import text_detection


def page(lines, fill="black", ground="white", size=(1400, 900)):
    image = Image.new("RGB", size, ground)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    for index, line in enumerate(lines):
        draw.text((60, 60 + index * 70), line, fill=fill, font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


LINES = ["The quarterly report of the company shows a rise", "in revenue over the year, and the board of",
         "directors approved the proposed budget for the", "next financial year after a long discussion",
         "of the expected costs in each of the regions"]


def test_a_blank_image_has_no_text_and_reads_nothing():
    found = text_detection.detect(page([]), lambda *_: pytest.fail("no read"))
    assert not found.has_text and found.script == "" and found.box_count == 0


def test_lines_of_latin_text_give_the_script_and_a_read():
    reads = []

    def read(stack, model):
        reads.append((stack.shape, model))
        return "read text"

    found = text_detection.detect(page(LINES), read)
    assert found.has_text and found.script == "Latin" and found.text == "read text"
    assert reads[0][1] == "Latin" and reads[0][0][0] > text_detection.STACK_LINE_HEIGHT


def test_light_text_on_a_dark_ground_gives_the_same_script():
    found = text_detection.detect(page(LINES, fill="white", ground="black"), lambda *_: "")
    assert found.script == "Latin"


def test_sideways_lines_give_the_same_script():
    with Image.open(io.BytesIO(page(LINES))) as image:
        output = io.BytesIO()
        image.rotate(90, expand=True).save(output, format="PNG")
    assert text_detection.detect(output.getvalue(), lambda *_: "").script == "Latin"


def evidence_of(*pairs):
    return list(pairs)


def test_a_low_confidence_vote_gives_no_script():
    assert text_detection._decide_script(evidence_of(("Malayalam", 0.45), ("Malayalam", 0.5), ("Hebrew", 0.5))) == ("", [])


def test_common_lines_do_not_vote_for_a_lone_rare_label():
    lines = evidence_of(*[("Common", 0.9)] * 5, ("Cherokee", 0.8))
    assert text_detection._decide_script(lines) == ("", [])


def test_divided_confident_lines_give_no_script():
    assert text_detection._decide_script(evidence_of(("Latin", 0.9), ("Hebrew", 0.9), ("Latin", 0.8), ("Hebrew", 0.8)))[0] == ""


def test_confident_lines_decide_and_han_models_share_a_script():
    assert text_detection._decide_script(evidence_of(("Hebrew", 0.9), ("Hebrew", 0.8), ("Latin", 0.3))) == ("Hebrew", [0, 1])
    assert text_detection._decide_script(evidence_of(("HanS", 0.9), ("HanT", 0.8), ("HanT", 0.8)))[0] == "HanT"


def test_a_short_page_can_decide_from_one_confident_line():
    assert text_detection._decide_script(evidence_of(("Greek", 0.9)))[0] == "Greek"


def test_a_sample_in_another_script_rejects_a_non_latin_result():
    assert not text_detection._script_of_sample("Malayalam", "Resolution of the Board and the undersigned")
    assert text_detection._script_of_sample("Malayalam", "മലയാളം ഭാഷ മനോഹരം ആകുന്നു")
    assert text_detection._script_of_sample("Malayalam", "short")
    assert text_detection._script_of_sample("Japanese", "ひらがな カタカナ 日本語の文章")


def test_an_upside_down_page_gives_the_same_script():
    with Image.open(io.BytesIO(page(LINES))) as image:
        output = io.BytesIO()
        image.rotate(180).save(output, format="PNG")
    assert text_detection.detect(output.getvalue(), lambda *_: "").script == "Latin"


def test_a_missing_script_model_skips_the_read():
    found = text_detection.detect(page(LINES), lambda *_: pytest.fail("no read"), available=["eng"])
    assert found.script == "Latin" and found.text == ""


def test_a_transparent_image_takes_a_white_ground():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    output = io.BytesIO()
    image.save(output, format="PNG")
    assert text_detection.decode_image(output.getvalue()).mean() == 255


def test_the_stack_stretches_contrast_on_a_white_page():
    line = np.full((30, 200, 3), 120, np.uint8)
    line[10:20, 20:180] = 100
    stack = text_detection._stack([line, line])
    assert stack.shape[0] == 2 * (text_detection.STACK_LINE_HEIGHT + text_detection.STACK_GUTTER) + text_detection.STACK_GUTTER
    assert stack.min() == 0 and stack.max() == 255


def test_the_route_reads_a_page_with_the_installed_script_model():
    answer = service.detect(service.DetectRequest(image_b64=base64.b64encode(page(LINES)).decode()))
    assert answer.has_text and answer.script == "Latin" and "report" in answer.text


def test_the_route_refuses_bytes_that_are_not_an_image():
    with pytest.raises(HTTPException) as error:
        service.detect(service.DetectRequest(image_b64=base64.b64encode(b"not an image").decode()))
    assert error.value.status_code == 422
