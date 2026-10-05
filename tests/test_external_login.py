from unittest.mock import patch

import pytest
import requests
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from gogstash import gog_auth
from gogstash.external_login import ExternalLoginDialog


SUCCESS_URL = "https://embed.gog.com/on_login_success?origin=client&code=thecode"
TOKEN = {"access_token": "abc", "refresh_token": "def", "expires_in": 3600, "expiry": 9999999999}


@pytest.fixture
def dialog():
    dialog = ExternalLoginDialog()
    dialog.show()
    yield dialog
    dialog.close()
    dialog.deleteLater()


@pytest.fixture
def shown_boxes(monkeypatch):
    # The dialog fires its warnings with show(), so nothing blocks, but a
    # headless test still shouldn't leave message boxes lying around. Keep
    # them for inspection instead.
    boxes = []
    monkeypatch.setattr(QMessageBox, "show", lambda box: boxes.append(box))
    return boxes


@pytest.fixture
def browser():
    with patch("gogstash.external_login.QDesktopServices.openUrl", return_value=True) as open_url:
        yield open_url


def test_step1_shows_login_address_from_the_start(dialog):
    assert dialog.step1_url.text() == gog_auth.build_auth_uri()
    assert dialog.step1_url.isReadOnly()
    # setText parks the cursor at the end, which scrolls the field to
    # "...layout=client2". Nobody recognises a URL by its ankles.
    assert dialog.step1_url.cursorPosition() == 0


def test_open_in_browser_opens_login_page(dialog, browser):
    dialog.step1_browser_button.click()

    browser.assert_called_once_with(QUrl(gog_auth.build_auth_uri()))


def test_copy_icon_copies_login_address(dialog):
    QGuiApplication.clipboard().setText("something else entirely")

    dialog.copy_action.trigger()

    assert QGuiApplication.clipboard().text() == gog_auth.build_auth_uri()


def test_paste_icon_replaces_whatever_was_in_the_field(dialog):
    # A built-in paste() would splice the new address into the leftovers of
    # the last attempt, and GOG doesn't accept collages.
    dialog.step2_url.setText("half of yesterday's address")
    QGuiApplication.clipboard().setText(SUCCESS_URL)

    dialog.paste_action.trigger()

    assert dialog.step2_url.text() == SUCCESS_URL


@patch("gogstash.gog_auth.fetch_token", return_value=TOKEN)
def test_log_in_saves_token_and_accepts(mock_fetch, dialog, shown_boxes):
    dialog.step2_url.setText(SUCCESS_URL)

    dialog.step2_login_button.click()

    mock_fetch.assert_called_once_with("thecode")
    assert gog_auth._load_token() == TOKEN
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert shown_boxes == []


@patch("gogstash.gog_auth.fetch_token", return_value=TOKEN)
def test_log_in_ignores_whitespace_around_pasted_address(mock_fetch, dialog, shown_boxes):
    # Address bars like to throw in a free space or newline with every copy.
    dialog.step2_url.setText(f"  {SUCCESS_URL} \n")

    dialog.step2_login_button.click()

    mock_fetch.assert_called_once_with("thecode")
    assert dialog.result() == QDialog.DialogCode.Accepted


@patch("gogstash.gog_auth.fetch_token", return_value=TOKEN)
def test_enter_in_paste_field_logs_in_instead_of_opening_browser(mock_fetch, dialog, browser, shown_boxes):
    # Regression: Open in Browser grabbed the default button role when it
    # got focus at startup and never gave it back, so pasting the address
    # and pressing Enter sent people off to log in all over again.
    dialog.step2_url.setFocus()
    dialog.step2_url.setText(SUCCESS_URL)

    QTest.keyClick(dialog.step2_url, Qt.Key.Key_Return)

    mock_fetch.assert_called_once_with("thecode")
    browser.assert_not_called()


@patch("gogstash.gog_auth.fetch_token")
def test_wrong_address_warns_without_asking_gog(mock_fetch, dialog, shown_boxes):
    dialog.step2_url.setText(gog_auth.build_auth_uri())

    dialog.step2_login_button.click()

    mock_fetch.assert_not_called()
    assert len(shown_boxes) == 1
    assert "not the right address" in shown_boxes[0].text()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()


@patch("gogstash.gog_auth.fetch_token", side_effect=KeyError("expires_in"))
def test_used_code_warns_and_keeps_dialog_open(mock_fetch, dialog, shown_boxes):
    # Regression: accept() used to run after the except blocks too, so the
    # dialog told people to start again from Step 1 and then vanished,
    # taking Step 1 with it.
    dialog.step2_url.setText(SUCCESS_URL)

    dialog.step2_login_button.click()

    assert len(shown_boxes) == 1
    assert "expired or was already used" in shown_boxes[0].text()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert gog_auth._load_token() is None


@patch("gogstash.gog_auth.fetch_token", side_effect=requests.exceptions.SSLError("certificate verify failed"))
def test_connection_problem_warns_with_the_real_error_type(mock_fetch, dialog, shown_boxes):
    # The browser got through, GogStash didn't. The details name the actual
    # culprit so a screenshot tells antivirus apart from proxy apart from
    # GOG having a bad day.
    dialog.step2_url.setText(SUCCESS_URL)

    dialog.step2_login_button.click()

    assert len(shown_boxes) == 1
    assert "couldn't reach GOG.com" in shown_boxes[0].text()
    assert shown_boxes[0].detailedText().startswith("SSLError:")
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert gog_auth._load_token() is None
