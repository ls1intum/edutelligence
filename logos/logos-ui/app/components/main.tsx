// Main.tsx
import React, { useContext } from 'react';
import { StyleSheet, Text, View, ScrollView, ImageBackground, Image, Dimensions, TouchableOpacity } from 'react-native';
import { ThemeContext } from '../';
import Section01 from './section01';
import Section02 from './section02';

const { width } = Dimensions.get('window');

const toolsLeft = ['Prompt Classification', 'Provider Routing', 'gRPC Interface'];
const toolsRight = ['REST API', 'Prompt Logging', 'Model Analytics'];

const faqData = [
  {
    question: 'What is Logos?',
    answer: 'Logos is a modular platform for processing, classifying, and routing prompts to large language models (LLMs).'
  },
  {
    question: 'Which providers are supported?',
    answer: 'Currently Azure, OpenWebUI, and OpenAI are supported with custom configuration.'
  }
];

export default function Main() {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';
  const [openIndex, setOpenIndex] = React.useState<number | null>(null);

  const toggleFAQ = (index: number) => {
    setOpenIndex(openIndex === index ? null : index);
  };

  return (
    <ScrollView style={[styles.wrapper, { backgroundColor: isLight ? '#fff' : '#121212' }]}>
      {/* Section 1: Hero Message */}
      <Section01/>

      {/* Section 2: Tools
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: isLight ? '#000' : '#fff' }]}>Available Tools</Text>
        <View style={styles.toolGrid}>
          <View style={styles.toolColumn}>
            <Text style={[styles.toolColumnTitle, { color: isLight ? '#000' : '#fff' }]}>Core Routing</Text>
            {toolsLeft.map((tool, idx) => (
              <Text key={idx} style={[styles.toolItem, { color: isLight ? '#222' : '#ccc' }]}>{tool}</Text>
            ))}
          </View>
          <View style={styles.toolColumn}>
            <Text style={[styles.toolColumnTitle, { color: isLight ? '#000' : '#fff' }]}>Data & APIs</Text>
            {toolsRight.map((tool, idx) => (
              <Text key={idx} style={[styles.toolItem, { color: isLight ? '#222' : '#ccc' }]}>{tool}</Text>
            ))}
          </View>
        </View>
      </View>
 */}
      <Section02/>
      {/* Section 3: Why Logos? */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: isLight ? '#000' : '#fff' }]}>Our Approach</Text>
        <Text style={[styles.sectionText, { color: isLight ? '#444' : '#ccc' }]}>
          Logos focuses on clarity, configurability, and extensibility. With unified APIs and routing policies,
          developers and organizations can integrate multiple LLMs seamlessly – securely and transparently.
        </Text>
      </View>

      {/* Section 4: FAQ */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: isLight ? '#000' : '#fff' }]}>FAQ</Text>
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
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    flex: 1
  },
  heroSection: {
    height: 300,
    justifyContent: 'center',
    alignItems: 'center'
  },
  overlay: {
    padding: 24,
    borderRadius: 12,
    alignItems: 'center'
  },
  heroTitle: {
    fontSize: 42,
    fontWeight: 'bold',
    textAlign: 'center'
  },
  heroSubtitle: {
    fontSize: 16,
    marginTop: 12,
    textAlign: 'center',
    maxWidth: '90%'
  },
  section: {
    padding: 20
  },
  sectionTitle: {
    fontSize: 22,
    fontWeight: 'bold',
    marginBottom: 16
  },
  sectionText: {
    fontSize: 16,
    lineHeight: 22
  },
  toolGrid: {
    flexDirection: 'row',
    justifyContent: 'space-between'
  },
  toolColumn: {
    flex: 1,
    paddingHorizontal: 10
  },
  toolColumnTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 8
  },
  toolItem: {
    fontSize: 16,
    paddingVertical: 4
  },
  faqItem: {
    marginBottom: 12
  },
  faqQuestion: {
    fontSize: 16,
    fontWeight: '600'
  },
  faqAnswer: {
    fontSize: 15,
    marginTop: 4
  }
});
