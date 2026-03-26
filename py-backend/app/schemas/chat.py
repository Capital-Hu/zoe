from pydantic import BaseModel


class ChatForm(BaseModel):
    userId: int
    memoryId: str
    message: str


class CompressMemoryForm(BaseModel):
    userId: int
    memoryId: str
