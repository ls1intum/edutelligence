import {Image, Text, View, StyleSheet, useColorScheme, useWindowDimensions} from "react-native";
import { Bolt, Code2, Users } from "lucide-react";
import { ThemeContext } from '../';
import {useContext} from "react";

export default function Section03() {
  const colorScheme = useColorScheme();
  const { width } = useWindowDimensions();
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  return (
    <View style={[styles.section, { backgroundColor: isLight ? '#e8e8e8' : '#212121' }]}>
      <View style={styles.content}>
        <Text style={[styles.badge, {backgroundColor: isLight ? '#fff' : '#000', color: isLight ? '#000' : '#fff'}]}>Our Approach</Text>
        <Text style={[styles.heading, {color: isLight ? '#000' : '#fff'}]}>Why Choose Logos?</Text>
        <Text style={[styles.description, {color: isLight ? '#000' : '#fff'}]}>
          Logos focuses on clarity, configurability, and extensibility. With unified APIs and routing policies,
          developers and organizations can integrate multiple LLMs seamlessly – securely and transparently.
        </Text>
        <View style={styles.bullets}>
          <View style={styles.bullet}>
            <Bolt color="#6366f1" size={20} style={styles.icon} />
            <View>
              <Text style={[styles.bulletTitle, {color: isLight ? '#000' : '#fff'}]}>Centralize control of your LLM deployments</Text>
              <Text style={[styles.bulletDescription, {color: isLight ? '#000' : '#fff'}]}>
                Gain actionable insights into LLM prompt performance
              </Text>
            </View>
          </View>
          <View style={styles.bullet}>
            <Users color="#6366f1" size={20} style={styles.icon} />
            <View>
              <Text style={[styles.bulletTitle, {color: isLight ? '#000' : '#fff'}]}>Track LLM utilization and identify areas for improvement</Text>
              <Text style={[styles.bulletDescription, {color: isLight ? '#000' : '#fff'}]}>
                Optimize your LLM usage for performance and cost
              </Text>
            </View>
          </View>
          <View style={styles.bullet}>
            <Code2 color="#6366f1" size={20} style={styles.icon} />
            <View>
              <Text style={[styles.bulletTitle, {color: isLight ? '#000' : '#fff'}]}>Standardize your LLM workflows for consistency and reliability</Text>
              <Text style={[styles.bulletDescription, {color: isLight ? '#000' : '#fff'}]}>
                Ensure model governance and compliance across your LLM initiatives
              </Text>
            </View>
          </View>
        </View>
      </View>
        {/*<Image source={mascotSource} style={styles.image} resizeMode="contain" />*/}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    paddingVertical: 80,
    paddingHorizontal: 24,
    backgroundColor: '#0a0a0a',
    alignItems: 'center',
  },
  badge: {
    alignItems: 'center',
    backgroundColor: '#1f2937',
    color: '#fff',
    paddingHorizontal: 12,
    paddingVertical: 4,
    fontSize: 12,
    borderRadius: 999,
    marginBottom: 10,
  },
  content: {
    flex: 1,
    alignItems: 'center',
    gap: 16,
  },
  tag: {
    color: "#6366f1",
    fontWeight: "600",
    fontSize: 14,
  },
  heading: {
    fontSize: 32,
    fontWeight: "bold",
    color: "#fff",
  },
  description: {
    maxWidth: 800,
    fontSize: 16,
    color: "#cbd5e1",
  },
  bullets: {
    gap: 20,
    marginTop: 8,
  },
  bullet: {
    flexDirection: "row",
    gap: 12,
    alignItems: "flex-start",
  },
  icon: {
    marginTop: 4,
  },
  bulletTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: "#fff",
  },
  bulletDescription: {
    fontSize: 14,
    color: "#cbd5e1",
  },
  cta: {
    marginTop: 16,
    alignSelf: "flex-start",
  },
  image: {
    height: 300,
    width: 300,
  },
});
