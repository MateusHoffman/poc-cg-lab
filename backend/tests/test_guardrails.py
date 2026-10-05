from app.guardrails import assess_faithfulness, redact_pii


def test_redacts_cpf_and_email():
    text = "Meu CPF é 123.456.789-09 e o email é ana@example.com."
    safe, count = redact_pii(text)
    assert count == 2
    assert "123.456.789-09" not in safe
    assert "ana@example.com" not in safe
    assert "[CPF PROTEGIDO]" in safe
    assert "[EMAIL PROTEGIDO]" in safe


def test_does_not_redact_vehicle_price():
    safe, count = redact_pii("Polo 2024 por 89990")
    assert count == 0
    assert safe == "Polo 2024 por 89990"


def test_flags_model_outside_retrieved_set():
    verdict = assess_faithfulness(
        "O Compass é a melhor escolha.",
        ["Polo", "Onix"],
    )
    assert verdict["faithful"] is False
    assert verdict["hallucinated"] == ["Compass"]
