from dataclasses import dataclass
from typing import Literal

@dataclass
class PaymentVerification:
    status: Literal["pending", "verified", "failed", "unsupported"]
    reference: str
    method: str
    message: str

class PaymentService:
    """Payment boundary for USDT, MTN MoMo and Telecel. Verification must be server-side."""
    def __init__(self, usdt_network: str, usdt_address: str, mtn_enabled: bool, telecel_enabled: bool):
        self.usdt_network = usdt_network
        self.usdt_address = usdt_address
        self.mtn_enabled = mtn_enabled
        self.telecel_enabled = telecel_enabled

    def verify_usdt(self, tx_hash: str) -> PaymentVerification:
        if not self.usdt_address:
            return PaymentVerification("unsupported", tx_hash, "USDT", "USDT receiving address is not configured.")
        return PaymentVerification("pending", tx_hash, "USDT", "Connect a blockchain verification provider before activating VIP.")

    def verify_momo(self, reference: str) -> PaymentVerification:
        if not self.mtn_enabled:
            return PaymentVerification("unsupported", reference, "MTN_MOMO", "MTN MoMo connector is disabled.")
        return PaymentVerification("pending", reference, "MTN_MOMO", "Connect the official merchant verification flow before activating VIP.")

    def verify_telecel(self, reference: str) -> PaymentVerification:
        if not self.telecel_enabled:
            return PaymentVerification("unsupported", reference, "TELECEL", "Telecel connector is disabled.")
        return PaymentVerification("pending", reference, "TELECEL", "Connect the official merchant verification flow before activating VIP.")
