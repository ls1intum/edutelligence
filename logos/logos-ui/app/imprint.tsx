import { ScrollView } from "react-native";
import Footer from "@/components/footer";
import Header from "@/components/header";

import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";

export default function Imprint() {
  return (
    <ScrollView
      contentContainerStyle={{
        flexGrow: 1,
        alignItems: "center",
        paddingVertical: 40,
        paddingHorizontal: 20,
      }}
    >
      <Box className="w-full max-w-[1440px]">
        <Text
          size="3xl"
          className="mb-6 text-left font-bold text-black dark:text-white"
        >
          Imprint
        </Text>

        <VStack space="lg">
          <Box>
            <Text
              size="md"
              className="mb-2 font-bold text-black dark:text-white"
            >
              Publisher
            </Text>
            <Text className="text-black dark:text-white">
              Technical University of Munich{"\n"}
              Postal address: Arcisstrasse 21, 80333 Munich{"\n"}
              Telephone: +49-(0)89-289-01{"\n"}
              Fax: +49-(0)89-289-22000{"\n"}
              Email: poststelle(at)tum.de
            </Text>
          </Box>

          <Box>
            <Text
              size="md"
              className="mb-2 font-bold text-black dark:text-white"
            >
              Authorized to represent
            </Text>
            <Text className="text-black dark:text-white">
              The Technical University of Munich is legally represented by the
              President Prof. Dr. Thomas F. Hofmann.
            </Text>
          </Box>

          <Box>
            <Text
              size="md"
              className="mb-2 font-bold text-black dark:text-white"
            >
              VAT identification number
            </Text>
            <Text className="text-black dark:text-white">
              DE811193231 (in accordance with § 27a of the German VAT tax act -
              UStG)
            </Text>
          </Box>

          <Box>
            <Text
              size="md"
              className="mb-2 font-bold text-black dark:text-white"
            >
              Responsible for content
            </Text>
            <Text className="text-black dark:text-white">
              Prof. Dr. Stephan Krusche{"\n"}
              Boltzmannstrasse 3{"\n"}
              85748 Garching
            </Text>
          </Box>

          <Box>
            <Text
              size="md"
              className="mb-2 font-bold text-black dark:text-white"
            >
              Terms of use
            </Text>
            <Text className="mb-2 text-black dark:text-white">
              Texts, images, graphics as well as the design of these Internet
              pages may be subject to copyright. The following are not protected
              by copyright according to §5 of copyright law (Urheberrechtsgesetz
              (UrhG)).
            </Text>
            <Text className="mb-2 text-black dark:text-white">
              Laws, ordinances, official decrees and announcements as well as
              decisions and officially written guidelines for decisions and
              other official works that have been published in the official
              interest for general knowledge, with the restriction that the
              provisions on prohibition of modification and indication of source
              in Section 62 (1) to (3) and Section 63 (1) and (2) UrhG apply
              accordingly.
            </Text>
            <Text className="text-black dark:text-white">
              As a private individual, you may use copyrighted material for
              private and other personal use within the scope of Section 53
              UrhG. Any duplication or use of objects such as images, diagrams,
              sounds or texts in other electronic or printed publications is not
              permitted without our agreement. This consent will be granted upon
              request by the person responsible for the content. The reprinting
              and evaluation of press releases and speeches are generally
              permitted with reference to the source. Furthermore, texts,
              images, graphics and other files may be subject in whole or in
              part to the copyright of third parties. The persons responsible
              for the content will also provide more detailed information on the
              existence of possible third-party rights.
            </Text>
          </Box>

          <Box>
            <Text
              size="md"
              className="mb-2 font-bold text-black dark:text-white"
            >
              Liability disclaimer
            </Text>
            <Text className="mb-2 text-black dark:text-white">
              The information provided on this website has been collected and
              verified to the best of our knowledge and belief. However, there
              will be no warranty that the information provided is up-to-date,
              correct, complete, and available. There is no contractual
              relationship with users of this website.
            </Text>
            <Text className="mb-2 text-black dark:text-white">
              We accept no liability for any loss or damage caused by using this
              website. The exclusion of liability does not apply where the
              provisions of the German Civil Code (BGB) on liability in case of
              breach of official duty are applicable (§ 839 of the BGB). We
              accept no liability for any loss or damage caused by malware when
              accessing or downloading data or the installation or use of
              software from this website.
            </Text>
            <Text className="text-black dark:text-white">
              Where necessary in individual cases: the exclusion of liability
              does not apply to information governed by the Directive
              2006/123/EC of the European Parliament and of the Council. This
              information is guaranteed to be accurate and up to date.
            </Text>
          </Box>

          <Box>
            <Text
              size="md"
              className="mb-2 font-bold text-black dark:text-white"
            >
              Links
            </Text>
            <Text className="text-black dark:text-white">
              Our own content is to be distinguished from cross-references
              (“links”) to websites of other providers. These links only provide
              access for using third-party content in accordance with § 8 of the
              German telemedia act (TMG). Prior to providing links to other
              websites, we review third-party content for potential civil or
              criminal liability. However, a continuous review of third-party
              content for changes is not possible, and therefore we cannot
              accept any responsibility. For illegal, incorrect, or incomplete
              content, including any damage arising from the use or non-use of
              third-party information, liability rests solely with the provider
              of the website.
            </Text>
          </Box>
        </VStack>
      </Box>
    </ScrollView>
  );
}
