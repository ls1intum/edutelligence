import { useContext } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { ThemeContext } from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';

export default function Imprint() {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  return (
      <View  style={styles.outer_container}>
          <Header />
        <View
      style={[
        styles.container, styles.outer_container,
        isLight ? styles.lightBackground : styles.darkBackground,
      ]}
    >
      <ScrollView style={styles.content}>
        <Text style={[styles.heading, isLight ? styles.lightText : styles.darkText]}>
          Privacy Policy
        </Text>

        <Text style={[styles.text, isLight ? styles.lightText : styles.darkText]}>
          <p>The Research Group for Applied Education Technologies (referred to as AET in the following paragraphs) from the
              Technical University of Munich takes the protection of private data seriously. We process the automatically collected
              personal data obtained when you visit our website, in compliance with the applicable data protection regulations, in
              particular the Bavarian Data Protection (BayDSG), the Telemedia Act (TMG) and the General Data Protection Regulation
              (GDPR). Below, we inform you about the type, scope and purpose of the collection and use of personal data.</p>
            <h2 id="logging">Logging</h2>
            <p>The web servers of the AET are operated by the AET itself, based in Boltzmannstr. 3, 85748 Garching b. Munich. Every
              time our website is accessed, the web server temporarily processes the following information in log files:</p>
            <ul>
              <li>IP address of the requesting computer</li>
              <li>Date and time of access</li>
              <li>Name, URL and transferred data volume of the accessed file</li>
              <li>Access status (requested file transferred, not found etc.)</li>
              <li>Identification data of the browser and operating system used (if transmitted by the requesting web browser)</li>
              <li>Website from which access was made (if transmitted by the requesting web browser)</li>
            </ul>
            <p>The processing of the data in this log file takes place as follows:</p>
            <ul>
              <li>The log entries are continuously updated automatically evaluated in order to be able to detect attacks on the web
                server and react accordingly.
              </li>
              <li>In individual cases, i.e. in the case of reported disruptions, errors and security incidents, a manual analysis is
                carried out.
              </li>
              <li>The IP addresses contained in the log entries are not merged with other databases by AET, so that no conclusions
                can be drawn about individual persons.
              </li>
            </ul>
            <h2 id="use-and-transfer-of-personal-data">Use and transfer of personal data</h2>
            <p>Our website can be used without providing personal data. All services that might require any form of personal data
              (e.g. registration for events, contact forms) are offered on external sites, linked here. The use of contact data
              published as part of the imprint obligation by third parties to send unsolicited advertising and information material
              is hereby prohibited. The operators of the pages reserve the right to take legal action in the event of the
              unsolicited sending of advertising information, such as spam mails.</p>
            <h2 id="revocation-of-your-consent-to-data-processing">Revocation of your consent to data processing</h2>
            <p>Some data processing operations require your express consent possible. You can revoke your consent that you have
              already given at any time. A message by e-mail is sufficient for the revocation. The lawfulness of the data processing
              that took place up until the revocation remains unaffected by the revocation.</p>
            <h2 id="right-to-file-a-complaint-with-the-responsible-supervisory-authority">Right to file a complaint with the
              responsible supervisory authority</h2>
            <p>You have the right to lodge a complaint with the responsible supervisory authority in the event of a breach of data
              protection law. The responsible supervisory authority with regard to data protection issues is the Federal
              Commissioner for Data Protection and Freedom of Information of the state where our company is based. The following
              link provides a list of data protection authorities and their contact details: <b><a style={styles.linkDarkText}
                href="https://www.bfdi.bund.de/DE/Infothek/Anschriften_Links/anschriften_links-node.html class=link--external"
            rel="noopener" target="_blank">https://www.bfdi.bund.de/DE/Infothek/Anschriften_Links/anschriften_links-node.html</a></b>.
            </p>
            <h2 id="right-to-data-portability">Right to data portability</h2>
            <p>You have the right to request the data that we process automatically on the basis of your consent or in fulfillment
              of a contract to be handed over to you or a third party. The data is provided in a machine-readable format. If you
              request the direct transfer of the data to another person responsible, this will only be done if it is technically
              feasible.</p>
            <h2 id="right-to-information-correction-blocking-and-deletion">Right to information, correction, blocking, and
              deletion</h2>
            <p>You have at any time within the framework of the applicable legal provisions the right to request information about
              your stored personal data, the origin of the data, its recipient and the purpose of the data processing, and if
              necessary, a right to correction, blocking or deletion of this data. You can contact us at any time via <b><a style={styles.linkDarkText}
                href="mailto:ls1.admin@in.tum.de">ls1.admin@in.tum.de</a></b> regarding this and other questions on the subject of
              personal data.</p>
            <h2 id="ssltls-encryption">SSL/TLS encryption</h2>
            <p>For security reasons and to protect the transmission of confidential content that you send to us send as a site
              operator, our website uses an SSL/TLS encryption. This means that data that you transmit via this website cannot be
              read by third parties. You can recognize an encrypted connection by the “https://” address line in your browser and by
              the lock symbol in the browser line.</p>
            <h2 id="e-mail-security">E-mail security</h2>
            <p>If you e-mail us, your e-mail address will only be used for correspondence with you. Please note that data
              transmission on the Internet can have security gaps. Complete protection of data from access by third parties is not
              possible.</p>
        </Text>
      </ScrollView>
    </View>
        <Footer />
      </View>

  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    paddingVertical: 40,
    paddingHorizontal: 20,
    alignItems: 'center',
  },
  outer_container: {
    flex: 1
  },
  content: {
    width: '100%',
    maxWidth: 1440,
  },
  heading: {
    fontSize: 32,
    fontWeight: 'bold',
    marginBottom: 24,
    textAlign: 'left',
  },
  text: {
    fontSize: 16,
    lineHeight: 24,
    fontFamily: '-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Oxygen,Ubuntu,Cantarell,Fira Sans,Droid Sans,Helvetica Neue,sans-serif'
  },
  lightBackground: {
    backgroundColor: '#ffffff',
  },
  darkBackground: {
    backgroundColor: '#1e1e1e',
  },
  lightText: {
    color: '#111111',
  },
  darkText: {
    color: '#f0f0f0',
  },
  linkDarkText: {
    color: '#ffffff',
  },
});