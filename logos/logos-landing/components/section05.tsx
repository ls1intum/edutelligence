import React, {useContext} from 'react';
import {View, Text, StyleSheet, useWindowDimensions, TouchableOpacity, Linking} from 'react-native';
import { ThemeContext } from './theme';

export default function Section05() {
  const { width } = useWindowDimensions();
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  const openExternalLink = () => {
    Linking.openURL('https://github.com/ls1intum/edutelligence');
  };

  return (
    <View style={[styles.container, { backgroundColor: isLight ? '#000000' : '#ffffff' }]}>
      <View style={styles.header}>
        <Text style={[styles.headline, {color: isLight ? '#fff' : '#000'}]}>Ready to Get Started?</Text>
        <Text style={[styles.subtext, {color: isLight ? '#fff' : '#000'}]}>
          Join our community and shape the future of LLM workflows.
        </Text>
      </View>
    <View style={styles.buttonRow}>
      <TouchableOpacity style={[styles.buttonPrimary, { backgroundColor: isLight ? '#fff' : '#000' }]} onPress={openExternalLink}>
        <Text style={[styles.buttonText, { color: isLight ? '#000' : '#fff' }]}>Get Started →</Text>
      </TouchableOpacity>

      {/*<TouchableOpacity style={[styles.buttonSecondary, { borderColor: isLight ? '#000' : '#fff' }]}>
        <Text style={[styles.buttonText, { color: isLight ? '#000' : '#fff' }]}>Learn More ⌄</Text>
      </TouchableOpacity>*/}
    </View>
      <View style={styles.header}>
        <Text style={[styles.subtext, {color: isLight ? '#fff' : '#000', fontSize: 16}]}>
          Open-source and free to use.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 80,
    paddingHorizontal: 24,
    backgroundColor: '#0a0a0a',
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
    fontSize: 38,
    fontWeight: 'bold',
    marginBottom: 10,
    textAlign: 'center',
  },
  subtext: {
    color: '#9ca3af',
    fontSize: 24,
    textAlign: 'center',
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 16,
      paddingBottom: 20,
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
