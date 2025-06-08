package com.zoe.java.ai.langchain4j;

import com.zoe.java.ai.langchain4j.assistant.SeparateChatAssistant;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
public class PromptTest {

    @Autowired
    private SeparateChatAssistant separateChatAssistant;

    @Test
    public void testSystemMessage() {
        String answer = separateChatAssistant.chat(3,"我是谁，今天几号");
        System.out.println(answer);
    }


    @Test
    public void testSystemMessage1() {
        String answer = separateChatAssistant.chat(4,"我是谁，今天几号");
        System.out.println(answer);
    }


    @Test
    public void testSystemMessage2() {
        String answer = separateChatAssistant.chat(5,"我是谁，今天几号");
        System.out.println(answer);
    }
}