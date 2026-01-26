---
layout: document
title: CCI data management at light microscopy
permalink: /docs/data_management_LM/
---

## Data management

After your imaging session, we encourage you to transfer all saved data to your transfer system ([OMERO]({{ '/omero_howto' | relative_url }}) or [NAS-Server]({{ '/docs/connect_cci_server' | relative_url }})). **After** transfer confirmation, please **delete** these data from the light microscope computer.

All CCI light microscope computers use an automatic cleanup and notification system to help keep the disks healthy and prevent data loss. As such:

 - **21 days after data acquisition**
    - Any data present on the microscope computer for more than 21 days will be moved to a temporary archive folder (D:\TMP).
    - When this happens, an email notification can be sent to you (see [Opt in Notifications](#opt-in-notifications) below)
 - **28 days after data acquisition**
    - If the data is still not moved off the microscope / not cleaned up by 28 days, it will be automatically deleted from the system.

**NOTE**: the microscope computers are not meant for long-term storage. This system is there to protect everyone’s ability to acquire data without running out of disk space.

## Vacation

In the case of a CCI-announced vacation period (notified by email), there is a **1-week (7 days)** grace period on top of the normal deadlines.

If you know you will be out-of-office and unable to check your data, please contact the CCI staff in advance so we can help you avoid accidental deletion.

If you receive a notification while you are away and cannot take action, contact the CCI staff as soon as possible.

## Opt-in notifications

Email notifications are **opt-in** and can be set up in three ways:

 - **Using your GU x-account**
    - If your data is stored in a top-level folder named with your x-account (e.g. xlecsi), the system can automatically send emails to your x-account@gu.se address.

 - **Using your email written as name_at_domain**
    - If your folder is named with your email in the form
firstname.lastname_at_gu.se or user_at_example.com,
the system will interpret _at_ as @ and send the notification there.

 - **Manual setup**
    - If neither option above applies, email the CCI staff with:
        - The **exact folder name** you use on the microscope computer
        - The **email address** you want notifications sent to

If you are unsure which option is best, feel free to contact CCI and we will help you set it up.

## Good practice

To reduce the risk of data loss and to avoid filling up microscope computer storage, please transfer your data off the microscope as soon as possible after acquisition.

For full details on data responsibility and storage policies, please refer to the [CCI User Rules]({{ '/user-rules' | relative_url }}).

**NOTE**: Omero and the NAS server are **not intended for long-term storage**. Data may be stored there for a **maximum of 28 days**, unless otherwise agreed with the CCI.
