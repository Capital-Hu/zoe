package com.zoe.java.al.langchain4j;

import dev.langchain4j.model.ollama.OllamaChatModel;
import dev.langchain4j.model.openai.OpenAiChatModel;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
public class LLMTest {

    /**
     * gpt-4o-mini语言模型接入测试
     */
    @Test
    public void testGPTDemo() {
        //初始化模型
        OpenAiChatModel model = OpenAiChatModel.builder()
                //LangChain4j提供的代理服务器，该代理服务器会将演示密钥替换成真实密钥， 再将请求转发给OpenAI API
                .baseUrl("http://langchain4j.dev/demo/openai/v1") //设置模型api地址（如果apiKey="demo"，则可省略baseUrl的配置）
                .apiKey("demo") //设置模型apiKey
                .modelName("gpt-4o-mini") //设置模型名称
                .build();

        //向模型提问
        String answer = model.chat("你是谁");
        //输出结果
        System.out.println(answer);
    }

    /**
     * 整合SpringBoot接入LLM的api
     */
    @Autowired
    private OpenAiChatModel openAiChatModel;
    //private ChatLanguageModel chatLanguageModel;//这个是父类
    @Test
    public void testSpringBoot() {
        //向模型提问
        String answer = openAiChatModel.chat("你是谁");
        //输出结果
        System.out.println(answer);
    }

    /**
     * ollama接入本地模型
     */
    @Autowired
    //private ChatLanguageModel chatLanguageModel;
    private OllamaChatModel ollamaChatModel;
    @Test
    public void testOllama() {
        //向模型提问
        String answer = ollamaChatModel.chat("你是谁");
        //输出结果
        System.out.println(answer);
    }
}
