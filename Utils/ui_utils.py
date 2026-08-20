"""Small UI helpers shared by HoTools modules."""


def popup_error(operator, message):
    operator.report({'ERROR'}, message)
