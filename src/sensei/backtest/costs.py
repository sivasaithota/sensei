"""Explicit current-cost delivery counterfactual for research, in INR."""

from sensei.execution.nse import IndianDeliveryChargeSchedule


def delivery_charge(notional: float, side: str, *, dp_charge_inr: float = 15.34) -> float:
    charges = IndianDeliveryChargeSchedule().calculate(
        turnover_paise=round(notional * 100), side=side,
    ).total_paise / 100
    return charges + (dp_charge_inr if side == "SELL" and notional > 0 else 0)


def delivery_quantity(*, price: float, stop: float, cash: float,
                      size_budget: float, risk_budget: float, dp_charge_inr: float,
                      quantity_step: int = 1) -> int:
    """Largest increment-aligned order satisfying cash and fee-inclusive risk."""
    if type(quantity_step) is not int or quantity_step <= 0:
        raise ValueError("quantity step must be a positive integer")
    low, high = 0, int(min(cash, size_budget) // price) // quantity_step
    while low < high:
        lots = (low + high + 1) // 2
        quantity = lots * quantity_step
        entry_fee = delivery_charge(quantity * price, "BUY", dp_charge_inr=dp_charge_inr)
        exit_fee = delivery_charge(quantity * stop, "SELL", dp_charge_inr=dp_charge_inr)
        if (quantity * price + entry_fee <= cash
                and quantity * (price - stop) + entry_fee + exit_fee <= risk_budget):
            low = lots
        else:
            high = lots - 1
    return low * quantity_step
