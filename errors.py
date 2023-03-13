class PassToUserException(Exception):
    def __init__(self, message="Сталась помилка, спробуй ще раз."):
        self.message = message
        super().__init__(self.message)