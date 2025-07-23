import React, {useContext, useEffect, useState} from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { ThemeContext } from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';
import { Image as ExpoImage } from 'expo-image';

export default function Imprint() {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  const [hue, setHue] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setHue(h => (h + 1) % 360);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
      <View  style={styles.outer_container}>
          <Header />
        <View
      style={[
        styles.container, styles.outer_container,
        isLight ? styles.lightBackground : styles.darkBackground,
      ]}
    >
        <ExpoImage
          source={require('../assets/images/logos_full.png')}
          style={[styles.logo, { filter: `hue-rotate(${hue}deg)` }]}
          contentFit="contain"
        />
        <Text style={[styles.title, isLight ? styles.lightText : styles.darkText]}>About Logos</Text>
          <Text style={[styles.paragraph, isLight ? styles.lightText : styles.darkText]}>
            Logos helps you organize and manage AI prompts by classifying and routing them to the right models – making it easier to build powerful, provider-agnostic AI workflows
          </Text>
          </View>
        <Footer />
      </View>

  );
}

const styles = StyleSheet.create({
  outer_container: {
    flex: 1,
    alignItems: 'center',
  },
  paragraph: {
    fontSize: 20,
    lineHeight: 24,
    marginBottom: 16,
    textAlign: 'center',
  },
  container: {
    flex: 1,
    padding: 24,
    alignItems: 'center',
    maxWidth: 800,
  },
  content: {
    width: '100%',
  },
  title: {
    fontSize: 28,
    marginBottom: 24,
    fontWeight: 'bold'
  },
  lightBackground: {
    backgroundColor: '#fff'
  },
  darkBackground: {
    backgroundColor: '#1e1e1e'
  },
  lightText: {
    color: '#000'
  },
  darkText: {
    color: '#fff'
  },
  buttonContainer: {
    width: '50%'
  },
  logo: {
    width: 200,
    height: 90
  }
});