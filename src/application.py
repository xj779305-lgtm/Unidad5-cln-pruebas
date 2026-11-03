class OrderService:
    def __init__(self, gateway):
        self.gateway = gateway

    def checkout(self, order):
        amount = order.confirm()
        if not self.gateway.charge(amount):
            raise RuntimeError("payment rejected")
        return amount
