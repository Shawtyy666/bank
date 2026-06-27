import os
import shutil
import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
WAIT_SECONDS = 15


@pytest.fixture
def driver():
    options = Options()

    # В CI браузер должен работать в headless-режиме.
    # Для локальной отладки можно запустить так: $env:HEADLESS="0"; python -m pytest -v
    if os.getenv("HEADLESS", "1") != "0":
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")

    chrome_binary = (
        os.getenv("CHROME_BINARY")
        or shutil.which("google-chrome")
        or shutil.which("chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if chrome_binary:
        options.binary_location = chrome_binary

    chromedriver_path = os.getenv("CHROMEDRIVER") or shutil.which("chromedriver")
    service = Service(executable_path=chromedriver_path) if chromedriver_path else Service()

    browser = webdriver.Chrome(service=service, options=options)
    yield browser
    browser.quit()


def wait(driver):
    return WebDriverWait(driver, WAIT_SECONDS)


def open_service(driver, balance=30000, reserved=20001):
    driver.get(f"{BASE_URL}/?balance={balance}&reserved={reserved}")
    wait(driver).until(
        EC.visibility_of_element_located((By.XPATH, "//h1[normalize-space()='F-Bank']"))
    )


def click_rub_account(driver):
    # Кликаем по заголовку счёта через JS. Так стабильнее, чем искать конкретный тег button,
    # потому что компонент UI-библиотеки может менять внутреннюю разметку.
    rub_title = wait(driver).until(
        EC.visibility_of_element_located((By.XPATH, "//h2[normalize-space()='Рубли']"))
    )
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
        rub_title,
    )
    wait(driver).until(
        EC.visibility_of_element_located((By.XPATH, "//input[@placeholder='0000 0000 0000 0000']"))
    )


def replace_input_value(element, value):
    element.click()
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(Keys.BACKSPACE)
    element.send_keys(str(value))


def fill_card(driver, card_number="1111111111111111"):
    card_input = wait(driver).until(
        EC.visibility_of_element_located((By.XPATH, "//input[@placeholder='0000 0000 0000 0000']"))
    )
    replace_input_value(card_input, card_number)
    wait(driver).until(
        EC.visibility_of_element_located((By.XPATH, "//input[@placeholder='1000']"))
    )


def set_amount(driver, amount):
    amount_input = wait(driver).until(
        EC.visibility_of_element_located((By.XPATH, "//input[@placeholder='1000']"))
    )
    replace_input_value(amount_input, amount)
    time.sleep(0.2)


def transfer_buttons(driver):
    return driver.find_elements(By.XPATH, "//button[normalize-space()='Перевести']")


def wait_transfer_button(driver):
    return wait(driver).until(
        EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Перевести']"))
    )


def prepare_transfer_form(driver, amount, balance=30000, reserved=20001):
    open_service(driver, balance=balance, reserved=reserved)
    click_rub_account(driver)
    fill_card(driver)
    set_amount(driver, amount)


def test_accounts_are_displayed_from_url_params(driver):
    open_service(driver, balance=30000, reserved=20001)

    assert driver.find_element(By.XPATH, "//h2[normalize-space()='Рубли']")
    assert driver.find_element(By.ID, "rub-sum").text == "30'000"
    assert driver.find_element(By.ID, "rub-reserved").text == "20'001"


def test_successful_rub_transfer_shows_alert(driver):
    prepare_transfer_form(driver, amount=1000)

    button = wait_transfer_button(driver)
    button.click()

    alert = wait(driver).until(EC.alert_is_present())
    assert "Перевод 1000 ₽" in alert.text
    assert "принят банком" in alert.text
    alert.accept()


def test_insufficient_funds_message_is_displayed(driver):
    prepare_transfer_form(driver, amount=10000)

    wait(driver).until(
        EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Недостаточно средств на счете")
    )
    assert not transfer_buttons(driver)


def test_negative_transfer_amount_is_rejected(driver):
    """
    Ожидаемое поведение: банк не должен разрешать перевод отрицательной суммы.
    Фактическое поведение: появляется кнопка «Перевести».
    На текущей версии сервиса тест должен падать.
    """
    prepare_transfer_form(driver, amount=-1000)

    assert not transfer_buttons(driver), "Дефект: сервис разрешает перевод отрицательной суммы"


def test_transfer_equal_to_available_amount_is_allowed(driver):
    """
    Доступный остаток: 30000 - 20001 = 9999.
    Сумма перевода: 9099.
    Комиссия: floor(9099 / 100) * 10 = 900.
    Итого: 9099 + 900 = 9999.

    Ожидаемое поведение: перевод разрешён, так как итоговая сумма не превышает доступный остаток.
    Фактическое поведение: сервис показывает «Недостаточно средств».
    На текущей версии сервиса тест должен падать.
    """
    prepare_transfer_form(driver, amount=9099)

    assert transfer_buttons(driver), (
        "Дефект: сервис запрещает перевод, когда сумма с комиссией ровно равна доступному остатку"
    )
