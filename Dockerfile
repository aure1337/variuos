FROM v2fly/v2fly-core:latest

COPY config.json /etc/v2ray/config.json                                                                                          
EXPOSE 8080                                                                                                                      
CMD ["v2ray", "run", "-c", "/etc/v2ray/config.json"]
