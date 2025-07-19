import React, {useContext, useEffect, useState} from 'react';
import {View, Text, StyleSheet, ActivityIndicator, Pressable, TouchableOpacity, ScrollView} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {ThemeContext} from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';
import Sidebar from '@/components/sidebar';
import {useRouter} from "expo-router";
import {compareSource} from "@expo/fingerprint/build/Sort";

export default function Policies() {
    const {theme} = useContext(ThemeContext);
    const [policies, setpolicies] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [isLoggedIn, setIsLoggedIn] = useState(false);
    const [apiKey, setApiKey] = useState('');
    const router = useRouter();

    useEffect(() => {
        const checkLogin = async () => {
            const key = await AsyncStorage.getItem('logos_api_key');
            if (!key) {
                requestAnimationFrame(() => {
                    router.replace('/');
                });
            } else {
                setIsLoggedIn(true);
                setApiKey(key);
                // Hier Daten laden
                loadpolicies();
            }
        };
        checkLogin();
    }, []);

    const loadpolicies = async () => {
        try {
            const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_policies', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${apiKey}`,
                    'Content-Type': 'application/json',
                    'logos_key': await AsyncStorage.getItem('logos_api_key'),
                },
                body: JSON.stringify({
                    logos_key: await AsyncStorage.getItem('logos_api_key')
                })
            });
            const [data, code] = JSON.parse(await response.text());
            if (code === 200) {
                const formattedpolicies = data.map((policy: any[][]) => ({
                    id: policy[0],
                    entity_id: policy[1],
                    name: policy[2],
                    description: policy[3],
                    threshold_privacy: policy[4],
                    threshold_latency: policy[5],
                    threshold_accuracy: policy[6],
                    threshold_cost: policy[7],
                    threshold_quality: policy[8],
                    priority: policy[9],
                    topic: policy[10],
                }));
                setpolicies(formattedpolicies);
            } else {
            }
            setLoading(false);
        } catch (e) {
            setpolicies([]);
        } finally {
            setLoading(false);
        }
    };

    if (!isLoggedIn) return null;

    return (
        <View style={styles.outer_container}>
            <ScrollView>
            <Header/>
            <View style={[styles.page, theme === 'light' ? styles.light : styles.dark]}>
                <Sidebar/>
                <View style={styles.content}>
                    <Text style={[styles.title, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Policies
                    </Text>
                    <Text style={[styles.subtitle, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Administrate policies.
                    </Text>
                    <View style={styles.statsContainer}>
                    </View>
                    <TouchableOpacity style={styles.addButton} onPress={() => router.push('/policies')}>
                        <Text style={styles.addButtonText}>+ Add</Text>
                    </TouchableOpacity>
                    {loading ? (
                        <ActivityIndicator size="large" color="#0000ff"/>
                    ) : (
                        <View style={styles.tableContainer}>
                            <Table policies={policies} theme={theme}/>
                        </View>
                    )}
                </View>
            </View>
        </ScrollView>
            <Footer/>
        </View>
    );
}

// @ts-ignore
const Table = ({policies, theme}) => {
    return (
        <table style={{
            borderCollapse: 'collapse',
            borderRadius: 10,
            overflow: 'hidden',
            boxShadow: '0px 0px 10px rgba(0,0,0,0.1)',
            backgroundColor: theme === 'light' ? '#fff' : '#333',
            color: theme === 'light' ? '#000' : '#fff',
        }}>
            <thead>
                <tr>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>ID</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Service-ID</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Name</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Description</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Threshold Privacy</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Threshold Latency</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Threshold Accuracy</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Threshold Cost</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Threshold Quality</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Priority</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Topic</th>
                </tr>
            </thead>
            <tbody>
                {policies.map((policy: any) => (
                    <tr key={policy.id}>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.id}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.entity_id}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.name}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.description}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.threshold_privacy}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.threshold_latency}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.threshold_accuracy}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.threshold_cost}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.threshold_quality}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.priority}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{policy.topic}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
};

const styles = StyleSheet.create({
    page: {
        flex: 1,
        flexDirection: 'row'
    },
    outer_container: {
        flex: 1
    },
    content: {
        flex: 1,
        padding: 32,
        width: '100%',
    },
    title: {
        fontSize: 28,
        fontWeight: 'bold',
        marginBottom: 24,
        alignSelf: 'center'
    },
    dummyCard: {
        marginTop: 20,
        alignSelf: 'center',
        padding: 20,
        borderRadius: 30,
        borderWidth: 1,
        borderColor: '#aaa'
    },
    light: {
        backgroundColor: '#fff'
    },
    dark: {
        backgroundColor: '#1e1e1e'
    },
    textLight: {
        color: '#000'
    },
    textDark: {
        color: '#fff'
    },subtitle: {
        fontSize: 16,
        color: '#666',
        marginBottom: 24,
    },
    statsContainer: {
        flexDirection: 'row',
        justifyContent: 'center',
        gap: 24,
        marginBottom: 32
    },
    statBox: {
        alignItems: 'center',
        backgroundColor: '#3c3c3c20',
        padding: 16,
        borderRadius: 16,
        minWidth: 100,
    },
    statNumber: {
        fontSize: 22,
        fontWeight: 'bold',
    },
    statLabel: {
        marginTop: 4,
        fontSize: 14,
    },
    addButton: {
        backgroundColor: '#007bff',
        padding: 12,
        borderRadius: 8,
        marginBottom: 24,
        alignSelf: 'flex-end',
    },
    addButtonText: {
        color: '#fff',
        fontSize: 18,
    },
    tableContainer: {
        overflow: 'scroll',
        overflowX: 'scroll',
        width: '100%',
        flex: 1,
        minWidth: 400
    },
    table: {
        borderWidth: 1,
        borderColor: '#ddd',
        borderRadius: 8,
        padding: 16,
    },
    tableHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        marginBottom: 12,
    },
    tableHeaderText: {
        fontSize: 18,
        fontWeight: 'bold',
    },
    tableRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingVertical: 8,
        borderBottomWidth: 1,
        borderColor: '#ddd',
    },
    tableCell: {
        fontSize: 16,
        borderRightWidth: 1,
        borderRightColor: '#ccc',
    },
    lasttableCell: {
        fontSize: 16,
    },
});