import React, {useContext} from 'react';
import {View, Text, StyleSheet, useWindowDimensions, TouchableOpacity} from 'react-native';
import { Linking } from 'react-native';
import { ThemeContext } from './theme';

const faqData = [
  {
    question: 'What is Logos?',
    answer: 'Logos is a modular platform for processing, classifying, and routing prompts to large language models (LLMs).'
  },
  {
    question: 'Which providers are supported?',
    answer: 'Currently Azure, OpenWebUI, and OpenAI are supported with custom configuration.'
  },
  {
    question: 'What data formats does your API support for requests and responses?',
    answer: 'Our API primarily supports JSON and gRPC for both requests and responses. JSON is the recommended and most actively maintained format. Please refer to the specific endpoint documentation for any format-specific details or constraints.'
  },
  {
    question: 'How do I handle authentication with your API?',
    answer: 'Authentication is required for most API endpoints. We utilize Logos-API keys for authentication. You can generate an API key over an API-endpoint or in this UI by providing a root key. Please include the "logos_key"-header in your requests, with your API key as the value.'
  },
  {
    question: 'Where can I find comprehensive documentation and code samples for your API?',
    answer: 'Our comprehensive API documentation is under the endpoint /docs. You’ll find detailed endpoint descriptions, request/response examples and code samples in python under the directory /src/scripts in the Logos Repo'
  }
]

export default function Section04() {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';
  const [openIndex, setOpenIndex] = React.useState<number | null>(null);
  const toggleFAQ = (index: number) => {
    setOpenIndex(openIndex === index ? null : index);
  };
  const openExternalLink = () => {
    Linking.openURL('https://github.com/ls1intum/edutelligence/discussions');
  };
  return (
      <View style={[styles.container, { backgroundColor: isLight ? '#ffffff' : '#121212' }]}>
        <Text style={[styles.badge, {backgroundColor: isLight ? '#ececec' : '#141f36', color: isLight ? '#000' : '#fff'}]}>Key Features</Text>
        <Text style={[styles.headline, { color: isLight ? '#000' : '#fff' }]}>FAQ</Text>
        {faqData.map((item, idx) => (
          <View key={idx} style={styles.faqItem}>
            <TouchableOpacity onPress={() => toggleFAQ(idx)}>
              <Text style={[styles.faqQuestion, { color: isLight ? '#000' : '#fff' }]}>{item.question}</Text>
            </TouchableOpacity>
            {openIndex === idx && (
              <Text style={[styles.faqAnswer, { color: isLight ? '#333' : '#bbb' }]}>{item.answer}</Text>
            )}
          </View>
        ))}
          <View style={[styles.end]}>
          </View>
          <View style={[styles.end, {backgroundColor: isLight ? '#cccccc' : '#303030'}]}>
              <Text style={[styles.text, {color: isLight ? '#000' : '#fff'}]}>Have more questions?</Text>
              <TouchableOpacity style={[styles.buttonPrimary, {backgroundColor: isLight ? '#f1f1f1' : '#5f5f5f'}]} onPress={openExternalLink}>
                  <Text style={[styles.buttonText, {color: isLight ? '#000' : '#fff'}]}>💡 Ask the Community</Text>
              </TouchableOpacity>
          </View>
      </View>
  );
}

const styles = StyleSheet.create({
    container: {
        paddingVertical: 80,
        paddingHorizontal: 24,
        backgroundColor: '#121212',
        alignItems: 'center',
    },
    header: {
        alignItems: 'center',
        marginBottom: 40,
    },
    badge: {
        backgroundColor: '#1f2937',
        color: '#fff',
        paddingHorizontal: 12,
        paddingVertical: 4,
        fontSize: 12,
        borderRadius: 999,
        marginBottom: 10,
    },
    headline: {
        color: '#fff',
        fontSize: 28,
        fontWeight: 'bold',
        marginBottom: 10,
        textAlign: 'center',
    },
    subtext: {
        color: '#9ca3af',
    fontSize: 16,
  },
  faqItem: {
    marginBottom: 12,
    width: 800
  },
  faqQuestion: {
    fontSize: 16,
    fontWeight: '600',
    textAlign: "left"
  },
  faqAnswer: {
    fontSize: 15,
    marginTop: 4
  },
  end: {
    paddingVertical: 40,
    paddingHorizontal: 24,
    alignItems: 'center',
    width: 800,
    borderRadius: 20
  },
  text: {
    fontSize: 20,
    textAlign: 'center',
    paddingVertical: 12,
  },

  buttonPrimary: {
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 8
  },
  buttonText: {
    fontSize: 16,
    fontWeight: '600',
  }
});
