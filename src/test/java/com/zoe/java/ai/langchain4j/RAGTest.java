package com.zoe.java.ai.langchain4j;

import dev.langchain4j.data.document.Document;
import dev.langchain4j.data.document.loader.FileSystemDocumentLoader;
import dev.langchain4j.data.document.parser.TextDocumentParser;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

import java.nio.file.FileSystems;
import java.nio.file.PathMatcher;
import java.util.List;

@SpringBootTest
public class RAGTest {
    @Test
    public void testReadDocument() {
        //使用FileSystemDocumentLoader读取指定目录下的知识库文档
        //并使用默认的文档解析器TextDocumentParser对文档进行解析
//        Document document = FileSystemDocumentLoader.loadDocument("C:/Users/a/Desktop/小智医疗/knowledge/测试.txt");
//        System.out.println(document.text());
//        // 加载单个文档
//        Document document = FileSystemDocumentLoader.loadDocument("C:/Users/a/Desktop/小智医疗/knowledge/file.txt", new TextDocumentParser());

//// 从一个目录中加载所有文档
//        List<Document> documents = FileSystemDocumentLoader.loadDocuments("C:/Users/a/Desktop/小智医疗/knowledge", new TextDocumentParser());

// 从一个目录中加载所有的.txt文档
        PathMatcher pathMatcher = FileSystems.getDefault().getPathMatcher("glob:*.txt");//md
        List<Document> documents = FileSystemDocumentLoader.loadDocuments("C:/Users/a/Desktop/小智医疗/knowledge", pathMatcher, new TextDocumentParser());
        for (Document document : documents) {
            System.out.println("=======================");
            System.out.println(document.metadata());
            System.out.println(document.text());
        }
//// 从一个目录及其子目录中加载所有文档
//        List<Document> documents = FileSystemDocumentLoader.loadDocumentsRecursively("C:/Users/a/Desktop/小智医疗/knowledge", new TextDocumentParser());
    }
}