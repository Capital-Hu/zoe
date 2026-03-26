from pydantic import BaseModel


class RegisterForm(BaseModel):
    username: str
    password: str


class LoginForm(BaseModel):
    username: str
    password: str
