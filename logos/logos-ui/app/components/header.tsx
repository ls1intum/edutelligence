import React, { useContext } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { ThemeContext } from '../';

export default function Header() {
  const { theme, toggleTheme } = useContext(ThemeContext);

  // Theme-abhängige Styles holen
  const isLight = theme === 'light';

  return (
    <View style={[styles.header, isLight ? styles.lightHeader : styles.darkHeader]}>
      {/* Linker Button zum Umschalten */}
      <TouchableOpacity
        onPress={toggleTheme}
        style={[styles.button, isLight ? styles.lightButton : styles.darkButton]}
      >
        <Text style={isLight ? styles.lightButtonText : styles.darkButtonText}>
          {isLight ? 'Dark Mode' : 'Light Mode'}
        </Text>
      </TouchableOpacity>

      {/* Rechts: Logos-Icon
      <Image
        source={require('../assets/logos-icon.png')}
        style={styles.icon}
        resizeMode="contain"
      />*/}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    width: '100%',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 12,
  },
  lightHeader: {
    backgroundColor: '#f5f5f5'
  },
  darkHeader: {
    backgroundColor: '#2a2a2a'
  },
  button: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 4,
    borderWidth: 1
  },
  lightButton: {
    backgroundColor: '#e0e0e0',
    borderColor: '#cccccc'
  },
  darkButton: {
    backgroundColor: '#3a3a3a',
    borderColor: '#555555'
  },
  lightButtonText: {
    color: '#111111',
    fontSize: 14
  },
  darkButtonText: {
    color: '#f0f0f0',
    fontSize: 14
  },
  icon: {
    width: 40,
    height: 40
  }
});
