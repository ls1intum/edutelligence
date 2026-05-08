import React, { useContext } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { ThemeContext } from './theme';

export default function Footer() {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  return (
    <View style={[styles.footer, isLight ? styles.lightFooter : styles.darkFooter]}>
      <Text style={[styles.footerContent, isLight ? styles.lightText : styles.darkText]}>
          <Text style={[styles.footerLeft, isLight ? styles.lightText : styles.darkText]}>
              <Text style={[styles.footerLeft, isLight ? styles.lightText : styles.darkText]}>
                <a href="/about" style={styles.citeText}><b>About</b></a>
              </Text>
              <Text style={[styles.footerLeft, isLight ? styles.lightText : styles.darkText]}>
                <a href="https://github.com/ls1intum/edutelligence" style={styles.citeText}><b>Releases</b></a>
              </Text>
              <Text style={[styles.footerLeft, isLight ? styles.lightText : styles.darkText]}>
                <a href="/privacy" style={styles.citeText}><b>Privacy</b></a>
              </Text>
              <Text style={[styles.footerLeft, isLight ? styles.lightText : styles.darkText]}>
                <a href="/imprint" style={styles.citeText}><b>Imprint</b></a>
              </Text>
          </Text>
          <Text style={[styles.footerRight, isLight ? styles.lightText : styles.darkText]}>
            Built by <a href="https://github.com/flbrgit" style={styles.citeText}><b>Florian Briksa</b></a> at <a href="https://www.tum.de/en/" style={styles.citeText}><b>TUM</b></a>.
            The source code is available on <a href="https://github.com/ls1intum/edutelligence" style={styles.citeText}><b>Github</b></a>.
          </Text>
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  footer: {
    width: '100%',
    padding: 12,
    borderTopWidth: 1
  },
  lightFooter: {
    backgroundColor: '#f5f5f5',
    borderTopColor: '#cccccc'
  },
  darkFooter: {
    backgroundColor: '#2a2a2a',
    borderTopColor: '#555555'
  },
  lightText: {
    color: '#111111',
    fontSize: 14
  },
  darkText: {
    color: '#f0f0f0',
    fontSize: 14
  },
  citeText: {
    color: '#969696'
  },
    footerContent: {
      alignSelf: 'center',
      width: '80%',
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
    },

    footerLeft: {
      textAlign: "left",
        paddingRight: 20,
    },

    footerRight: {
      textAlign: "right",
    }
});
