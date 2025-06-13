plugins {
    id("java")
    id("maven-publish")
}

group = "de.tum.cit.aet.artemis"
version = "1.0.0"

java {
    withSourcesJar()
}

tasks.register<Jar>("protoJar") {
    archiveClassifier.set("proto")
    from("src/proto-release") // Directory containing proto files
    include("*.proto")
}

publishing {
    publications {
        create<MavenPublication>("proto") {
            artifactId = "artemis-proto"
            artifact(tasks["protoJar"])
            groupId = project.group.toString()
            version = project.version.toString()
        }
    }

    repositories {
        maven {
            url = uri("https://your-nexus-or-maven-central-url/")
            credentials {
                username = "..."
                password = "..."
            }
        }
    }
}
