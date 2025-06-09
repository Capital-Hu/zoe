package com.zoe.java.ai.langchain4j.assistant;

import dev.langchain4j.service.*;
import dev.langchain4j.service.spring.AiService;

import static dev.langchain4j.service.spring.AiServiceWiringMode.EXPLICIT;

@AiService(
        wiringMode = EXPLICIT,
        chatModel = "qwenChatModel",
        chatMemoryProvider = "chatMemoryProviderZoe")
public interface ZoeAgent {
	
	@SystemMessage(fromResource = "zoe-prompt-template.txt")
    String chat(@MemoryId Long memoryId, @UserMessage String userMessage);
}