// HeroSection.tsx
import React, { useContext } from 'react';
import {View, Text, StyleSheet, TouchableOpacity, useWindowDimensions, Linking} from 'react-native';
import { ThemeContext } from '../';

export default function Section01() {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  const openExternalLink = () => {
    Linking.openURL('https://github.com/ls1intum/edutelligence');
  };

  return (
    <View style={[styles.container, { backgroundColor: isLight ? '#e8e8e8' : '#212121' }]}>
      <View style={styles.content}>
        <Text style={[styles.headline, { color: isLight ? '#000' : '#fff' }]}>
          Your Gateway to Scalable AI Infrastructure
        </Text>
        <Text style={[styles.subtext, { color: isLight ? '#333' : '#ccc' }]}>
          Connect, log, and control prompt routing for efficient LLM usage across providers
        </Text>

        <View style={styles.buttonRow}>
          <TouchableOpacity style={[styles.buttonPrimary, { backgroundColor: isLight ? '#000' : '#fff' }]} onPress={openExternalLink}>
            <Text style={[styles.buttonText, { color: isLight ? '#fff' : '#000' }]}>Get Started →</Text>
          </TouchableOpacity>

          {/*<TouchableOpacity style={[styles.buttonSecondary, { borderColor: isLight ? '#000' : '#fff' }]}>
            <Text style={[styles.buttonText, { color: isLight ? '#000' : '#fff' }]}>Learn More ⌄</Text>
          </TouchableOpacity>*/}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 80,
    paddingHorizontal: 24,
    alignItems: 'center',
    justifyContent: 'center'
  },
  content: {
    maxWidth: 800,
    alignItems: 'center'
  },
  headline: {
    fontSize: 42,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 20
  },
  subtext: {
    fontSize: 16,
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 30
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 16
  },
  buttonPrimary: {
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 8
  },
  buttonSecondary: {
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 8,
    borderWidth: 1
  },
  buttonText: {
    fontSize: 16,
    fontWeight: '600'
  }
});
